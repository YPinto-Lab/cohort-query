"""Utility script to scrape Metalog metadata schema from metalog.embl.de.

Usage:
    python scripts/scrape_metalog.py

Generates:
    Accessors/MetalogAccessor/metalog_human_schema.json
"""
import requests
from lxml import html
import json
import re
from pathlib import Path

BASE_URL = 'https://metalog.embl.de'
METADATA_URL = f'{BASE_URL}/metadata/human'

# Output to the MetalogAccessor directory
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_FILE = PROJECT_ROOT / 'Accessors/MetalogAccessor/metalog_human_schema.json'


def scrape_metalog_fields():
    """
    Scrapes all metadata fields from the MetaLog human metadata page.
    Returns a list of fields with their names, categories, and documentation links.
    """
    response = requests.get(METADATA_URL)
    response.raise_for_status()
    tree = html.fromstring(response.content)

    fields = []
    
    # Find all links that point to documentation pages (pattern: /metadata/human/core/field_name)
    doc_links = tree.xpath('//a[contains(@href, "/metadata/human/core/")]')
    
    for link in doc_links:
        href = link.get('href')
        # Extract field name from the URL
        match = re.search(r'/metadata/human/core/([^/]+)$', href)
        if match:
            field_name = match.group(1)
            doc_url = f'{BASE_URL}{href}' if href.startswith('/') else href
            
            # Determine category by finding the parent section heading
            category = determine_category(link)
            
            # Avoid duplicates
            if not any(f['field_name'] == field_name for f in fields):
                fields.append({
                    'field_name': field_name,
                    'category': category,
                    'documentation_url': doc_url
                })
    
    # Also look for additional metadata fields in tables
    # These are field names in the first column of tables that don't have /core/ links
    tables = tree.xpath('//table')
    for table in tables:
        rows = table.xpath('.//tr')
        for row in rows:
            cells = row.xpath('.//td')
            if cells:
                # First cell contains the field name
                field_text = cells[0].text_content().strip()
                # Clean up field name (remove extra whitespace)
                field_name = field_text.split()[0] if field_text.split() else None
                
                if field_name and not any(f['field_name'] == field_name for f in fields):
                    # Check if there's a link for this field
                    field_links = cells[0].xpath('.//a[contains(@href, "/metadata/human/")]')
                    if field_links:
                        href = field_links[0].get('href')
                        if '/core/' in href:
                            continue  # Already processed above
                    
                    # For additional fields without /core/ links, construct documentation URL
                    category = determine_category(row)
                    doc_url = f'{BASE_URL}/metadata/human/core/{field_name}'
                    
                    fields.append({
                        'field_name': field_name,
                        'category': category,
                        'documentation_url': doc_url
                    })

    return fields


def determine_category(element):
    """
    Determines if a field belongs to 'core' or 'additional' category
    by looking at preceding headings.
    """
    try:
        # Get all preceding h2 elements
        preceding_h2 = element.xpath('preceding::h2')
        if preceding_h2:
            last_h2 = preceding_h2[-1].text_content().lower()
            if 'additional' in last_h2:
                return 'additional'
            elif 'curated' in last_h2 or 'core' in last_h2:
                return 'core'
    except Exception:
        pass
    return 'unknown'


def save_schema(fields, output_file=OUTPUT_FILE):
    """Saves the fields to a JSON schema file."""
    schema = {
        'source': METADATA_URL,
        'fields': fields
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    
    print(f'Saved {len(fields)} fields to {output_file}')


if __name__ == '__main__':
    fields = scrape_metalog_fields()
    save_schema(fields)
    print(json.dumps({'fields': fields}, indent=2))









