"""
This module contains the MetalogAccessor class, responsible for loading and providing
access to the Metalog metadata schema.

Following the iDesign architecture pattern, this accessor fetches configuration data
(the Metalog schema) and provides it to other layers in a consistent format.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MetalogField:
    """Represents a single field from the Metalog schema."""
    field_name: str
    category: str
    documentation_url: str


class MetalogAccessor:
    """
    Accessor for loading and querying the Metalog human metadata schema.
    
    The schema contains field definitions scraped from metalog.embl.de,
    including field names, categories, and documentation URLs.
    """
    
    # Default path is relative to this accessor's directory
    DEFAULT_SCHEMA_PATH = Path(__file__).parent / "metalog_human_schema.json"
    
    def __init__(self, schema_path: Optional[Path] = None):
        """
        Initialize the accessor with the schema file path.
        
        Args:
            schema_path: Path to the metalog schema JSON file.
                        Defaults to 'metalog_human_schema.json' in the project root.
        """
        self.schema_path = schema_path or self.DEFAULT_SCHEMA_PATH
        self._fields: List[MetalogField] = []
        self._docs_lookup: Dict[str, str] = {}
        self._loaded = False
    
    def load(self) -> "MetalogAccessor":
        """
        Load the schema from the JSON file.
        
        Returns:
            Self for method chaining.
            
        Raises:
            FileNotFoundError: If the schema file doesn't exist.
        """
        if not self.schema_path.exists():
            raise FileNotFoundError(
                f"Metalog schema not found at '{self.schema_path}'. "
                "Please run the scraper first: python scraper.py"
            )
        
        with open(self.schema_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        self._fields = [
            MetalogField(
                field_name=f['field_name'],
                category=f.get('category', 'unknown'),
                documentation_url=f.get('documentation_url', '')
            )
            for f in data.get('fields', [])
        ]
        
        self._docs_lookup = {f.field_name: f.documentation_url for f in self._fields}
        self._loaded = True
        
        return self
    
    @property
    def fields(self) -> List[MetalogField]:
        """Get all fields from the schema."""
        if not self._loaded:
            self.load()
        return self._fields
    
    @property
    def field_names(self) -> List[str]:
        """Get a list of all field names."""
        return [f.field_name for f in self.fields]
    
    @property
    def documentation_urls(self) -> Dict[str, str]:
        """Get a mapping of field names to their documentation URLs."""
        if not self._loaded:
            self.load()
        return self._docs_lookup
    
    def get_documentation_url(self, field_name: str) -> Optional[str]:
        """
        Get the documentation URL for a specific field.
        
        Args:
            field_name: The name of the field to look up.
            
        Returns:
            The documentation URL, or None if the field doesn't exist.
        """
        return self.documentation_urls.get(field_name)
    
    def __len__(self) -> int:
        """Return the number of fields in the schema."""
        return len(self.fields)
