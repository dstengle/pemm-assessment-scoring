import argparse
import logging
from collections import defaultdict
from typing import Dict, List, Any
import pandas as pd
from googleapiclient.errors import HttpError

# Import the new Google Auth function
from google_auth import get_sheets_service

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# --- USER CONFIGURABLE VALUES ---
# Please update these with your actual Google Sheet IDs and ranges
DEFAULT_QUESTIONS_SHEET_ID = "YOUR_QUESTIONS_SPREADSHEET_ID_HERE"
DEFAULT_QUESTIONS_SHEET_RANGE = "Sheet1!A:F"  # Assuming Question, Category, L1, L2, L3, L4
DEFAULT_RESPONSES_SHEET_ID = "YOUR_RESPONSES_SPREADSHEET_ID_HERE"
DEFAULT_RESPONSES_SHEET_RANGE = "Form Responses 1!A:Z"  # Adjust as per your responses sheet structure
DEFAULT_SCORES_OUTPUT_SHEET_ID = "YOUR_SCORES_OUTPUT_SPREADSHEET_ID_HERE"
DEFAULT_SCORES_OUTPUT_SHEET_RANGE = "CalculatedScores!A1" # Sheet name and starting cell for scores
# --- END USER CONFIGURABLE VALUES ---

class AssessmentScorer:
    def __init__(self, questions_sheet_id: str, questions_sheet_range: str,
                 responses_sheet_id: str, responses_sheet_range: str,
                 scores_output_sheet_id: str, scores_output_sheet_range: str):
        self.questions_sheet_id = questions_sheet_id
        self.questions_sheet_range = questions_sheet_range
        self.responses_sheet_id = responses_sheet_id
        self.responses_sheet_range = responses_sheet_range
        self.scores_output_sheet_id = scores_output_sheet_id
        self.scores_output_sheet_range = scores_output_sheet_range
        
        self.service = get_sheets_service() # Initialize Google Sheets service
        if not self.service:
            # get_sheets_service() already logs errors, so we can just raise here
            raise RuntimeError("Failed to initialize Google Sheets service. Check credentials and google_auth.py.")

        self.question_map: Dict[str, Dict[str, Any]] = {}
        self.unmatched_answer_count = 0
        self.responses_processed_count = 0

    def _normalize_text(self, text: str) -> str:
        """Helper to normalize text for comparison."""
        return str(text).strip().lower() # Ensure text is string before stripping

    def _fetch_sheet_data(self, spreadsheet_id: str, range_name: str) -> pd.DataFrame:
        """Fetches data from Google Sheets and returns it as a pandas DataFrame."""
        try:
            sheet = self.service.spreadsheets()
            result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
            values = result.get('values', [])

            if not values:
                logging.warning(f"No data found in sheet ID '{spreadsheet_id}' range '{range_name}'.")
                return pd.DataFrame()
            
            # Assuming the first row is headers
            headers = values[0]
            data = values[1:]
            df = pd.DataFrame(data, columns=headers)
            return df
        except HttpError as err:
            logging.error(f"Google API error fetching sheet ID '{spreadsheet_id}', range '{range_name}': {err}")
            if err.resp.status == 403:
                logging.error("Ensure the Google Sheets API is enabled for your project and the service account has access to the sheet.")
            elif err.resp.status == 404:
                logging.error(f"Sheet ID '{spreadsheet_id}' or range '{range_name}' not found. Please verify.")
            raise # Re-raise the exception to be handled by the caller
        except Exception as e:
            logging.error(f"An unexpected error occurred fetching sheet ID '{spreadsheet_id}', range '{range_name}': {e}")
            raise

    def load_questions(self) -> None:
        """Load questions from the Google Sheet and build internal mappings."""
        logging.info(f"Loading questions from Google Sheet ID: '{self.questions_sheet_id}', Range: '{self.questions_sheet_range}'")
        try:
            questions_df = self._fetch_sheet_data(self.questions_sheet_id, self.questions_sheet_range)
            if questions_df.empty:
                logging.error("No questions data loaded from Google Sheets. Cannot proceed.")
                return

            for index, row in questions_df.iterrows():
                question = row.get('Question', '').strip() # Ensure 'Question' matches your sheet header
                category = row.get('Category', '').strip() # Ensure 'Category' matches your sheet header

                if not question or not category:
                    logging.debug(f"Skipping row {index+2} with empty question or category: {row.to_dict()}")
                    continue

                if "(original)" in question.lower():
                    logging.debug(f"Skipping original question: {question}")
                    continue

                normalized_question = self._normalize_text(question)
                
                answers = {}
                for i in range(1, 5): # L1 to L4
                    level_key = f"L{i}" # Ensure 'L1', 'L2', etc. match your sheet headers
                    answer_text = row.get(level_key, '') 
                    if pd.notna(answer_text) and str(answer_text).strip(): # Check for non-empty and non-NA
                        answers[i] = self._normalize_text(str(answer_text))
                
                if not answers:
                    logging.warning(f"Question '{question}' (Row {index+2}) has no L1-L4 answers defined. Skipping.")
                    continue

                self.question_map[normalized_question] = {
                    "category": category,
                    "answers": answers,
                    "original_question_text": question
                }
            logging.info(f"Successfully loaded {len(self.question_map)} questions from Google Sheet.")
        except Exception as e:
            logging.error(f"Error loading questions from Google Sheet: {e}")
            # No raise here, as _fetch_sheet_data would have raised for API errors
            # This catches errors during DataFrame processing

    def load_responses(self) -> List[Dict[str, str]]:
        """Load response data from the Google Sheet."""
        logging.info(f"Loading responses from Google Sheet ID: '{self.responses_sheet_id}', Range: '{self.responses_sheet_range}'")
        responses_list = []
        try:
            responses_df = self._fetch_sheet_data(self.responses_sheet_id, self.responses_sheet_range)
            if responses_df.empty:
                logging.info("No responses data loaded from Google Sheets.")
                return []

            # Convert DataFrame rows to list of dictionaries
            for index, row in responses_df.iterrows():
                # Ensure all values are strings, handle NaN/None by converting to empty string
                responses_list.append({str(col): str(val) if pd.notna(val) else '' for col, val in row.items()})
            
            logging.info(f"Successfully loaded {len(responses_list)} responses from Google Sheet.")
            return responses_list
        except Exception as e:
            logging.error(f"Error loading responses from Google Sheet: {e}")
            return [] # Return empty list on error after fetching

    def find_maturity_level(self, question_text: str, response_answer_text: str) -> int:
        normalized_question = self._normalize_text(question_text)
        normalized_response_answer = self._normalize_text(response_answer_text)

        question_data = self.question_map.get(normalized_question)
        if not question_data:
            # This can happen if a response column header doesn't match any loaded question
            # Or if the question was skipped during loading (e.g. no L1-L4 answers)
            logging.debug(f"Question text '{question_text}' (normalized: '{normalized_question}') not found in question_map. Skipping for this response.")
            return 0

        maturity_options = question_data["answers"]
        for level, option_text in maturity_options.items():
            if option_text == normalized_response_answer:
                return level
        
        logging.info(f"Unmatched answer for question '{question_data['original_question_text']}': Response answer '{response_answer_text}' (normalized: '{normalized_response_answer}') did not match any L1-L4 options {maturity_options}. Skipping this answer.")
        self.unmatched_answer_count += 1
        return 0

    def score_response(self, response_row: Dict[str, str]) -> tuple[Dict[str, float], str]:
        category_scores = defaultdict(list)
        
        timestamp = response_row.get('Timestamp', 'N/A') # Assuming 'Timestamp' is a column in your responses sheet
        logging.info(f"\nProcessing response (Timestamp: {timestamp})")

        for question_header, response_answer in response_row.items():
            # Standardize common non-question columns to skip
            if not question_header or question_header.lower() in ['timestamp', 'score', 'email address', 'name'] or not str(response_answer).strip():
                continue

            normalized_header = self._normalize_text(question_header)
            # Check if the normalized header (potential question) is in our loaded question_map
            if normalized_header in self.question_map:
                category = self.question_map[normalized_header]["category"]
                score = self.find_maturity_level(question_header, str(response_answer)) # Ensure response_answer is string
                if score > 0:
                    category_scores[category].append(score)
            else:
                # This logs if a column header from responses sheet is not a recognized question
                logging.debug(f"Response column header '{question_header}' not found in loaded questions map. Skipping this column for scoring.")

        averaged_scores: Dict[str, float] = {}
        for category, scores in category_scores.items():
            if scores:
                averaged_scores[category] = sum(scores) / len(scores)
                logging.info(f"Category '{category}': Average Score = {averaged_scores[category]:.2f} (from scores: {scores})")
            else:
                logging.info(f"Category '{category}': No valid answers matched for scoring.")
        
        if not averaged_scores:
            logging.info("No scores calculated for this response (no matched answers for any category).")
            
        return averaged_scores, timestamp

    def write_scores_to_sheet(self, scores_data: List[List[str]]) -> None:
        """Write calculated scores to a Google Sheet."""
        if not scores_data:
            logging.info("No scores data to write to sheet.")
            return
            
        logging.info(f"Writing {len(scores_data)} score records to Google Sheet ID: '{self.scores_output_sheet_id}', Range: '{self.scores_output_sheet_range}'")
        
        try:
            # First, try to get the sheet to see if it exists
            sheet = self.service.spreadsheets()
            
            # Parse the range to extract sheet name
            sheet_name = self.scores_output_sheet_range.split('!')[0] if '!' in self.scores_output_sheet_range else 'CalculatedScores'
            
            # Try to get sheet metadata to check if the target sheet exists
            try:
                spreadsheet = sheet.get(spreadsheetId=self.scores_output_sheet_id).execute()
                sheet_exists = any(s['properties']['title'] == sheet_name for s in spreadsheet['sheets'])
            except HttpError as err:
                if err.resp.status == 404:
                    logging.error(f"Spreadsheet ID '{self.scores_output_sheet_id}' not found. Please verify the ID.")
                    raise
                elif err.resp.status == 403:
                    logging.error("Access denied. Ensure the service account has write permissions to the output sheet.")
                    raise
                else:
                    raise
            
            # Create the sheet if it doesn't exist
            if not sheet_exists:
                logging.info(f"Sheet '{sheet_name}' does not exist. Creating it...")
                request_body = {
                    'requests': [{
                        'addSheet': {
                            'properties': {
                                'title': sheet_name
                            }
                        }
                    }]
                }
                sheet.batchUpdate(spreadsheetId=self.scores_output_sheet_id, body=request_body).execute()
                logging.info(f"Successfully created sheet '{sheet_name}'")
            
            # Write the data to the sheet
            value_input_option = 'RAW'
            body = {
                'values': scores_data
            }
            
            result = sheet.values().update(
                spreadsheetId=self.scores_output_sheet_id,
                range=self.scores_output_sheet_range,
                valueInputOption=value_input_option,
                body=body
            ).execute()
            
            logging.info(f"Successfully wrote scores to sheet. Updated {result.get('updatedCells', 0)} cells.")
            
        except HttpError as err:
            logging.error(f"Google API error writing scores to sheet: {err}")
            if err.resp.status == 403:
                logging.error("Ensure the service account has write permissions to the output sheet.")
            elif err.resp.status == 400:
                logging.error(f"Invalid range '{self.scores_output_sheet_range}' or data format. Please verify.")
            raise
        except Exception as e:
            logging.error(f"An unexpected error occurred writing scores to sheet: {e}")
            raise

    def process_all_responses(self) -> None:
        """Load questions, load responses, and score each response using Google Sheets."""
        all_scores = []
        
        try:
            self.load_questions()
            if not self.question_map:
                logging.error("No questions loaded. Aborting processing.")
                return
                
            responses = self.load_responses()
            if not responses:
                logging.info("No responses to process.")
                return

            # Prepare header row for scores output
            categories = set()
            for question_data in self.question_map.values():
                categories.add(question_data["category"])
            
            sorted_categories = sorted(categories)
            header_row = ["Timestamp", "Respondent ID"] + sorted_categories + ["Overall Score"]
            all_scores.append(header_row)

            for i, response_row in enumerate(responses):
                logging.info(f"--- Scoring Response {i+1}/{len(responses)} ---")
                scores, timestamp = self.score_response(response_row)
                self.responses_processed_count += 1
                
                # Create output row
                respondent_id = response_row.get('Email Address', response_row.get('Name', f'Response_{i+1}'))
                output_row = [timestamp, respondent_id]
                
                # Add category scores
                category_total = 0
                category_count = 0
                for category in sorted_categories:
                    if category in scores:
                        score_value = round(scores[category], 2)
                        output_row.append(str(score_value))
                        category_total += score_value
                        category_count += 1
                    else:
                        output_row.append("N/A")
                
                # Calculate overall score
                overall_score = round(category_total / category_count, 2) if category_count > 0 else 0
                output_row.append(str(overall_score))
                
                all_scores.append(output_row)
            
            # Write scores to sheet
            if len(all_scores) > 1:  # More than just the header
                self.write_scores_to_sheet(all_scores)
            
            logging.info(f"\n--- Processing Summary ---")
            logging.info(f"Total responses processed: {self.responses_processed_count}")
            logging.info(f"Total unmatched answers (skipped during scoring): {self.unmatched_answer_count}")

        except RuntimeError as e: # Catch specific RuntimeError from service init
            logging.error(f"Critical setup error: {e}")
        except Exception as e:
            logging.error(f"An critical error occurred during processing: {e}", exc_info=True)

def main():
    parser = argparse.ArgumentParser(description="Score assessment responses from Google Sheets.")
    parser.add_argument(
        '--questions_sheet_id',
        default=DEFAULT_QUESTIONS_SHEET_ID,
        help=f"Google Sheet ID for the question set. Default: {DEFAULT_QUESTIONS_SHEET_ID}"
    )
    parser.add_argument(
        '--questions_sheet_range',
        default=DEFAULT_QUESTIONS_SHEET_RANGE,
        help=f"Sheet name and range for questions (e.g., 'Sheet1!A:F'). Default: {DEFAULT_QUESTIONS_SHEET_RANGE}"
    )
    parser.add_argument(
        '--responses_sheet_id',
        default=DEFAULT_RESPONSES_SHEET_ID,
        help=f"Google Sheet ID for the responses. Default: {DEFAULT_RESPONSES_SHEET_ID}"
    )
    parser.add_argument(
        '--responses_sheet_range',
        default=DEFAULT_RESPONSES_SHEET_RANGE,
        help=f"Sheet name and range for responses (e.g., 'Form Responses 1!A:Z'). Default: {DEFAULT_RESPONSES_SHEET_RANGE}"
    )
    parser.add_argument(
        '--scores_output_sheet_id',
        default=DEFAULT_SCORES_OUTPUT_SHEET_ID,
        help=f"Google Sheet ID for writing calculated scores. Default: {DEFAULT_SCORES_OUTPUT_SHEET_ID}"
    )
    parser.add_argument(
        '--scores_output_sheet_range',
        default=DEFAULT_SCORES_OUTPUT_SHEET_RANGE,
        help=f"Sheet name and range for score output (e.g., 'CalculatedScores!A1'). Default: {DEFAULT_SCORES_OUTPUT_SHEET_RANGE}"
    )
    args = parser.parse_args()

    if "YOUR_SPREADSHEET_ID_HERE" in args.questions_sheet_id or \
       "YOUR_SPREADSHEET_ID_HERE" in args.responses_sheet_id or \
       "YOUR_SPREADSHEET_ID_HERE" in args.scores_output_sheet_id:
        logging.error("Placeholder Sheet IDs detected. Please update DEFAULT_QUESTIONS_SHEET_ID, "
                      "DEFAULT_RESPONSES_SHEET_ID, and DEFAULT_SCORES_OUTPUT_SHEET_ID in the script, "
                      "or provide them as command-line arguments.")
        return

    scorer = AssessmentScorer(
        questions_sheet_id=args.questions_sheet_id,
        questions_sheet_range=args.questions_sheet_range,
        responses_sheet_id=args.responses_sheet_id,
        responses_sheet_range=args.responses_sheet_range,
        scores_output_sheet_id=args.scores_output_sheet_id,
        scores_output_sheet_range=args.scores_output_sheet_range
    )
    scorer.process_all_responses()

if __name__ == "__main__":
    main()