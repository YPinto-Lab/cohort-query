"""
TaxonomyAccessor: Handles taxonomy lineage database construction and retrieval.

This module builds a lineage database from taxonomy data using the nested set model
(ileft/iright columns) to efficiently compute ancestor relationships for any tax_id.
"""
import pandas as pd
import csv
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any


class TaxonomyAccessor:
    """
    Accessor for taxonomy lineage information.
    Builds and queries a lineage database that maps tax_id -> list of ancestors.
    """
    
    STANDARD_RANKS = ['superkingdom', 'phylum', 'class', 'order', 'family', 'genus', 'species']
    
    def __init__(self, lineage_db_path: Optional[Path] = None):
        """
        Initialize the TaxonomyAccessor.
        
        Args:
            lineage_db_path: Path to pre-built lineage JSON database. If None, must call build_from_df.
        """
        self._lineage_db: Dict[str, List[Dict[str, Any]]] = {}
        self._db_path = lineage_db_path
        
        if lineage_db_path and lineage_db_path.exists():
            self.load_database(lineage_db_path)
    
    def load_database(self, path: Path) -> None:
        """Load an existing lineage database from JSON."""
        with open(path, 'r') as f:
            self._lineage_db = json.load(f)
        print(f"✅ Loaded lineage database with {len(self._lineage_db)} taxa")
    
    def save_database(self, path: Path) -> None:
        """Save the lineage database to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self._lineage_db, f, indent=2)
        print(f"✅ Saved lineage database to {path}")
    
    def build_from_dataframe(self, df: pd.DataFrame) -> None:
        """
        Build lineage database directly from a DataFrame containing taxonomy data.
        
        Expected columns: tax_id, rank, name, ileft, iright, acc (for grouping)
        
        Args:
            df: DataFrame with taxonomy columns
        """
        required_cols = {'tax_id', 'rank', 'name', 'ileft', 'iright', 'acc'}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        print(f"Building lineage database from {len(df)} rows...")
        
        # Group by accession (each acc has its own nested set)
        processed_accs = 0
        
        for acc, group in df.groupby('acc'):
            rows = group.to_dict('records')
            self._process_acc_group(rows)
            processed_accs += 1
            if processed_accs % 100 == 0:
                print(f"  Processed {processed_accs} accessions. Found {len(self._lineage_db)} unique taxa.")
        
        print(f"✅ Built lineage database with {len(self._lineage_db)} unique taxa")
    
    def _process_acc_group(self, rows: List[Dict[str, Any]]) -> None:
        """
        For a group of rows belonging to one accession, compute lineages.
        Uses nested set model: ancestor has ileft <= node.ileft AND iright >= node.iright
        """
        for node in rows:
            tid = str(node['tax_id'])
            if tid in self._lineage_db:
                continue
            
            # Find ancestors in this group
            n_ileft = node['ileft']
            n_iright = node['iright']
            
            ancestors = []
            for cand in rows:
                if cand['ileft'] <= n_ileft and cand['iright'] >= n_iright:
                    ancestors.append(cand)
            
            # Sort ancestors by ileft ASC (root first), then iright DESC
            ancestors.sort(key=lambda x: (x['ileft'], -x['iright']))
            
            # Clean up ancestor list, handling NaN values
            clean_ancestors = []
            for a in ancestors:
                rank = a['rank']
                name = a['name']
                # Convert NaN to empty string
                rank_str = str(rank) if rank == rank else ''  # NaN check: x != x for NaN
                name_str = str(name) if name == name else ''
                clean_ancestors.append({
                    'rank': rank_str,
                    'name': name_str,
                    'tax_id': str(a['tax_id'])
                })
            
            self._lineage_db[tid] = clean_ancestors
    
    def build_from_csv(self, input_csv: str, output_json: str) -> None:
        """
        Builds a lineage database from a CSV file.
        
        Expected CSV columns (by index):
        0: acc, 1: tax_id, 2: rank, 3: name, 7: ileft, 8: iright
        
        Args:
            input_csv: Path to input CSV
            output_json: Path to save the lineage database
        """
        sorted_csv = input_csv + ".sorted"
        
        if not os.path.exists(sorted_csv):
            print(f"Sorting {input_csv} by accession...")
            cmd = f"tail -n +2 {input_csv} | sort -t, -k1,1 > {sorted_csv}"
            try:
                subprocess.run(cmd, shell=True, check=True, env={**os.environ, 'LC_ALL': 'C'})
            except subprocess.CalledProcessError as e:
                print(f"Error sorting file: {e}")
                return
        else:
            print(f"Using existing sorted file: {sorted_csv}")
        
        print("Processing sorted file to extract lineages...")
        
        current_acc = None
        acc_rows = []
        processed_accs = 0
        
        with open(sorted_csv, 'r') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                
                try:
                    acc = row[0]
                    tax_id = row[1]
                    rank = row[2]
                    name = row[3]
                    ileft = int(row[7])
                    iright = int(row[8])
                except (IndexError, ValueError):
                    continue
                
                if acc != current_acc:
                    if current_acc is not None:
                        self._process_acc_group(acc_rows)
                        processed_accs += 1
                        if processed_accs % 100 == 0:
                            print(f"  Processed {processed_accs} accessions. Found {len(self._lineage_db)} unique taxa.")
                    current_acc = acc
                    acc_rows = []
                
                acc_rows.append({
                    'tax_id': tax_id,
                    'rank': rank,
                    'name': name,
                    'ileft': ileft,
                    'iright': iright
                })
            
            # Process last group
            if current_acc and acc_rows:
                self._process_acc_group(acc_rows)
        
        print(f"✅ Extracted lineages for {len(self._lineage_db)} taxa")
        self.save_database(Path(output_json))
    
    def get_lineage(self, tax_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Returns the full lineage for a given tax_id.
        
        Args:
            tax_id: Taxonomy ID (as string)
            
        Returns:
            List of ancestor dicts with 'rank', 'name', 'tax_id', or None if not found
        """
        return self._lineage_db.get(str(tax_id))
    
    def get_ancestor_at_rank(self, tax_id: str, target_rank: str) -> Optional[Dict[str, Any]]:
        """
        Get the ancestor of a tax_id at a specific taxonomic rank.
        
        Args:
            tax_id: Taxonomy ID
            target_rank: Target rank (e.g., 'genus', 'family', 'phylum')
            
        Returns:
            Dict with 'rank', 'name', 'tax_id' or None if not found
        """
        lineage = self.get_lineage(tax_id)
        if not lineage:
            return None
        
        for ancestor in lineage:
            if ancestor['rank'].lower() == target_rank.lower():
                return ancestor
        return None
    
    def aggregate_counts_at_rank(self, df: pd.DataFrame, target_rank: str,
                                  tax_id_col: str = 'tax_id',
                                  count_col: str = 'total_count',
                                  sample_col: str = 'acc') -> pd.DataFrame:
        """
        Aggregate abundance counts at a specific taxonomic rank.
        
        Args:
            df: DataFrame with taxonomy abundance data
            target_rank: Rank to aggregate to (e.g., 'genus', 'family')
            tax_id_col: Column containing tax_id
            count_col: Column containing counts
            sample_col: Column containing sample identifiers
            
        Returns:
            DataFrame with columns: sample, taxon_name, taxon_id, count
        """
        aggregated = []
        
        for _, row in df.iterrows():
            tax_id = str(row[tax_id_col])
            ancestor = self.get_ancestor_at_rank(tax_id, target_rank)
            
            if ancestor:
                aggregated.append({
                    'sample': row[sample_col],
                    'taxon_name': ancestor['name'],
                    'taxon_id': ancestor['tax_id'],
                    'count': row[count_col]
                })
            else:
                # If no ancestor at this rank, use 'Unclassified'
                aggregated.append({
                    'sample': row[sample_col],
                    'taxon_name': f'Unclassified ({target_rank})',
                    'taxon_id': 'NA',
                    'count': row[count_col]
                })
        
        result_df = pd.DataFrame(aggregated)
        
        # Aggregate counts for same sample + taxon
        result_df = result_df.groupby(['sample', 'taxon_name', 'taxon_id'], as_index=False)['count'].sum()
        
        return result_df
    
    def get_available_ranks(self) -> List[str]:
        """
        Get all unique ranks present in the lineage database.
        
        Returns:
            Sorted list of rank names
        """
        ranks = set()
        for lineage in self._lineage_db.values():
            for ancestor in lineage:
                rank = ancestor.get('rank')
                if rank and isinstance(rank, str):
                    ranks.add(rank)
        
        # Sort by standard rank order if possible
        rank_order = {r: i for i, r in enumerate(self.STANDARD_RANKS)}
        sorted_ranks = sorted(ranks, key=lambda r: rank_order.get(r.lower(), 999))
        
        return sorted_ranks
    
    @property
    def database(self) -> Dict[str, List[Dict[str, Any]]]:
        """Access the raw lineage database."""
        return self._lineage_db
    
    def __len__(self) -> int:
        return len(self._lineage_db)
