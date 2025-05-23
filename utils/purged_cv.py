"""Purged k-fold cross-validation for time series data."""

import numpy as np
from sklearn.model_selection import KFold

class PurgedKFold(KFold):
    """Walk-forward CV with purging of overlapping samples."""
    
    def __init__(self, n_splits=5, purge_window=200, shuffle=False, random_state=None):
        super().__init__(n_splits=n_splits, shuffle=shuffle, random_state=random_state)
        self.purge_window = purge_window
        
    def split(self, X, y=None, groups=None):
        indices = np.arange(len(X))
        
        # Generate fold boundaries
        fold_size = len(indices) // self.n_splits
        test_starts = range(0, len(indices), fold_size)
        
        for fold_start in test_starts:
            # Test indices for this fold
            test_end = min(fold_start + fold_size, len(indices))
            test_idx = indices[fold_start:test_end]
            
            # Training indices excluding the purge window
            train_idx = np.concatenate([
                indices[:max(0, fold_start - self.purge_window)],
                indices[test_end + self.purge_window:]
            ])
            
            yield train_idx, test_idx 