#!/usr/bin/env python3
"""
Command-line interface for viewing Google Sheet tabs.

This script prompts the user for a Google Sheet ID and displays
the names of all tabs (sheets) in that spreadsheet.
"""

import sys
from sheets_util import get_sheet_tabs


def main():
    """Main function for the CLI script."""
    print("Google Sheets Tab Viewer")
    print("=" * 25)
    print()
    
    # Prompt user for Google Sheet ID
    try:
        sheet_id = input("Enter Google Sheet ID: ").strip()
        
        if not sheet_id:
            print("Error: Sheet ID cannot be empty.")
            return 1
            
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 1
    
    print(f"\nFetching tabs for sheet ID: {sheet_id}")
    print()
    
    try:
        # Call the get_sheet_tabs function
        tab_names = get_sheet_tabs(sheet_id)
        
        if tab_names:
            # Display the tab names
            print(f"Found {len(tab_names)} tab(s):")
            print("-" * 30)
            for i, tab_name in enumerate(tab_names, 1):
                print(f"{i}. {tab_name}")
        else:
            # Empty list returned - could be no tabs, sheet not found, or permissions issue
            print("No tabs found.")
            print("This could mean:")
            print("- The sheet ID is invalid or the sheet doesn't exist")
            print("- The sheet has no tabs (unlikely)")
            print("- You don't have permission to access this sheet")
            print("- There was a network or API issue")
        
        return 0
        
    except ValueError as e:
        # Input validation error
        print(f"Input Error: {e}")
        return 1
        
    except Exception as e:
        # Authentication or other critical errors
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "credentials" in error_msg.lower():
            print(f"Authentication Error: {e}")
            print("Please check your Google API credentials and authentication setup.")
        elif "access denied" in error_msg.lower() or "permission" in error_msg.lower():
            print(f"Permission Error: {e}")
            print("Make sure the sheet is shared with your account or is publicly accessible.")
        else:
            print(f"Error: {e}")
        
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)