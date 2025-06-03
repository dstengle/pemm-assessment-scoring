"""
Utility functions for interacting with Google Sheets API.
"""

from google_auth import get_sheets_service
from googleapiclient.errors import HttpError


def get_sheet_tabs(sheet_id):
    """
    Fetch the names of all individual sheets (tabs) from a Google Spreadsheet.
    
    Args:
        sheet_id (str): The Google Sheet ID to fetch metadata for.
        
    Returns:
        list: A list of sheet names (tab names) from the spreadsheet.
              Returns an empty list if there are errors or no sheets found.
              
    Raises:
        ValueError: If sheet_id is None or empty string.
        Exception: For authentication errors or other critical failures.
    """
    # Input validation
    if not sheet_id or not isinstance(sheet_id, str):
        raise ValueError("Sheet ID must be a non-empty string")
    
    # Strip whitespace from sheet_id
    sheet_id = sheet_id.strip()
    if not sheet_id:
        raise ValueError("Sheet ID must be a non-empty string")
    
    try:
        # Get authenticated service object
        service = get_sheets_service()
        if not service:
            raise Exception("Failed to authenticate with Google Sheets API")
        
        # Fetch spreadsheet metadata
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        
        # Extract sheet names from metadata
        sheets = spreadsheet.get('sheets', [])
        sheet_names = []
        
        for sheet in sheets:
            properties = sheet.get('properties', {})
            title = properties.get('title', '')
            if title:  # Only add non-empty titles
                sheet_names.append(title)
        
        return sheet_names
        
    except HttpError as error:
        # Handle specific Google API errors
        error_details = error.error_details if hasattr(error, 'error_details') else []
        
        if error.resp.status == 404:
            # Sheet not found
            return []
        elif error.resp.status == 403:
            # Permission denied
            raise Exception(f"Access denied to spreadsheet {sheet_id}. Check permissions and authentication.")
        elif error.resp.status == 400:
            # Bad request (likely invalid sheet ID format)
            return []
        else:
            # Other HTTP errors
            raise Exception(f"Google Sheets API error: {error}")
            
    except Exception as error:
        # Handle other errors (authentication, network, etc.)
        if "authentication" in str(error).lower() or "credentials" in str(error).lower():
            raise Exception(f"Authentication error: {error}")
        else:
            # For other unexpected errors, return empty list as fallback
            return []