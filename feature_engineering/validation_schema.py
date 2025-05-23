"""Validation schema for L2 features."""

import pandera as pa
import numpy as np

# Create schema for L2 features
L2FeaturesSchema = pa.DataFrameSchema({
    # Price-based features
    'rel_spread': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'spread_ma': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'spread_std': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'spread_ticks': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    
    # Volume imbalance features
    'vol_imb': pa.Column(float, checks=[
        pa.Check.in_range(-1, 1)
    ]),
    'ofi_1': pa.Column(float),
    'ofi_3': pa.Column(float),
    'ofi_10': pa.Column(float),
    
    # Moving averages of OFI
    'ofi_1_ma': pa.Column(float),
    'ofi_3_ma': pa.Column(float),
    'ofi_10_ma': pa.Column(float),
    
    # OFI volatility
    'ofi_1_std': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'ofi_3_std': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'ofi_10_std': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    
    # Microprice features
    'mp_slope': pa.Column(float),
    'mp_accel': pa.Column(float),
    'flow_mp_slope': pa.Column(float),
    
    # Queue position features
    'bid_depth_ratio_1': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'ask_depth_ratio_1': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'bid_depth_ratio_2': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    'ask_depth_ratio_2': pa.Column(float, checks=[
        pa.Check.greater_than_or_equal_to(0)
    ]),
    
    # Fill probability
    'fill_prob': pa.Column(float, checks=[
        pa.Check.in_range(0, 1)
    ])
}, strict=True, coerce=True)

# Example usage:
# df = pd.DataFrame({...})
# validated_df = L2FeaturesSchema.validate(df) 