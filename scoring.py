import csv
import argparse
import logging
from collections import defaultdict
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

class AssessmentScorer:
    def __init__(self, questions_file: str, responses_file: str):
        self.questions_file = questions_file
        self.responses_file = responses_file
        # question_map: {question_text_normalized: {"category": str, "answers": {1: answer_l1_norm, 2: answer_l2_norm, ...}}}
        self.question_map: Dict[str, Dict[str, Any]] = {}
        self.unmatched_answer_count = 0
        self.responses_processed_count = 0

    def _normalize_text(self, text: str) -> str:
        """Helper to normalize text for comparison."""
        return text.strip().lower()

    def load_questions(self) -> None:
        """Load questions from the CSV file and build internal mappings."""
        try:
            with open(self.questions_file, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    question = row.get('Question', '').strip()
                    category = row.get('Category', '').strip()

                    if not question or not category:
                        logging.debug(f"Skipping row with empty question or category: {row}")
                        continue

                    if "(original)" in question.lower():
                        logging.debug(f"Skipping original question: {question}")
                        continue

                    normalized_question = self._normalize_text(question)
                    
                    answers = {}
                    for i in range(1, 5): # L1 to L4
                        level_key = f"L{i}"
                        answer_text = row.get(level_key, '').strip()
                        if answer_text: # Only add if answer text is present
                            answers[i] = self._normalize_text(answer_text)
                    
                    if not answers: # Skip question if it has no defined answers for L1-L4
                        logging.warning(f"Question '{question}' has no L1-L4 answers defined. Skipping.")
                        continue

                    self.question_map[normalized_question] = {
                        "category": category,
                        "answers": answers,
                        "original_question_text": question # For logging/debugging
                    }
            logging.info(f"Successfully loaded {len(self.question_map)} questions from '{self.questions_file}'.")
        except FileNotFoundError:
            logging.error(f"Error: Questions file not found at '{self.questions_file}'.")
            raise
        except Exception as e:
            logging.error(f"Error loading questions from '{self.questions_file}': {e}")
            raise
            
    def load_responses(self) -> List[Dict[str, str]]:
        """Load response data from the CSV file."""
        responses = []
        try:
            with open(self.responses_file, mode='r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    responses.append(row)
            logging.info(f"Successfully loaded {len(responses)} responses from '{self.responses_file}'.")
            return responses
        except FileNotFoundError:
            logging.error(f"Error: Responses file not found at '{self.responses_file}'.")
            raise
        except Exception as e:
            logging.error(f"Error loading responses from '{self.responses_file}': {e}")
            raise
        return []

    def find_maturity_level(self, question_text: str, response_answer_text: str) -> int:
        """
        Match response answer text to a maturity level for a given question.
        Returns the maturity level (1-4) or 0 if not matched.
        """
        normalized_question = self._normalize_text(question_text)
        normalized_response_answer = self._normalize_text(response_answer_text)

        question_data = self.question_map.get(normalized_question)
        if not question_data:
            logging.warning(f"Question '{question_text}' not found in question set. Skipping for this response.")
            return 0

        maturity_options = question_data["answers"] # {1: "norm_ans1", 2: "norm_ans2", ...}
        for level, option_text in maturity_options.items():
            if option_text == normalized_response_answer:
                return level
        
        logging.info(f"Unmatched answer for question '{question_data['original_question_text']}': Response answer '{response_answer_text}' did not match any L1-L4 options. Skipping this answer.")
        self.unmatched_answer_count += 1
        return 0

    def score_response(self, response_row: Dict[str, str]) -> Dict[str, float]:
        """Calculate average scores for each category for a single response row."""
        category_scores = defaultdict(list) # category: [score1, score2, ...]
        
        timestamp = response_row.get('Timestamp', 'N/A')
        print(f"\nTimestamp: {timestamp}")

        for question_header, response_answer in response_row.items():
            if question_header.lower() in ['timestamp', 'score'] or not response_answer.strip():
                continue

            normalized_header = self._normalize_text(question_header)
            if normalized_header in self.question_map:
                category = self.question_map[normalized_header]["category"]
                score = self.find_maturity_level(question_header, response_answer)
                if score > 0:
                    category_scores[category].append(score)
            else:
                # This case should ideally be caught by find_maturity_level if question_header is a valid question
                # but good to have a fallback log if the header itself is not in question_map
                logging.debug(f"Response column header '{question_header}' not found in loaded questions. Skipping.")


        averaged_scores: Dict[str, float] = {}
        for category, scores in category_scores.items():
            if scores:
                averaged_scores[category] = sum(scores) / len(scores)
                print(f"{category}: {averaged_scores[category]:.2f}")
            else:
                # This handles cases where a category had questions, but none were answered or matched
                print(f"{category}: No valid answers")
        
        if not averaged_scores:
            print("No scores calculated for this response.")
            
        return averaged_scores

    def process_all_responses(self) -> None:
        """Load questions, load responses, and score each response."""
        try:
            self.load_questions()
            if not self.question_map:
                logging.error("No questions loaded. Aborting processing.")
                return
                
            responses = self.load_responses()
            if not responses:
                logging.info("No responses to process.")
                return

            for response_row in responses:
                self.score_response(response_row)
                self.responses_processed_count += 1
            
            logging.info(f"\n--- Processing Summary ---")
            logging.info(f"Total responses processed: {self.responses_processed_count}")
            logging.info(f"Total unmatched answers (skipped): {self.unmatched_answer_count}")

        except Exception as e:
            logging.error(f"An critical error occurred during processing: {e}")

def main():
    parser = argparse.ArgumentParser(description="Score assessment responses based on a question set.")
    parser.add_argument(
        '-q', '--questions',
        required=True,
        help="Path to the question set CSV file."
    )
    parser.add_argument(
        '-r', '--responses',
        required=True,
        help="Path to the responses CSV file."
    )
    args = parser.parse_args()

    scorer = AssessmentScorer(
        questions_file=args.questions,
        responses_file=args.responses
    )
    scorer.process_all_responses()

if __name__ == "__main__":
    main()