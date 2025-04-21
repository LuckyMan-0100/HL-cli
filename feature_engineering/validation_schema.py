import pandera as pa
from pandera.typing import Series
import pandas as pd

class L2FeaturesSchema(pa.SchemaModel):
    """Validation schema for L2 features."""
    
    symbol: Series[str] = pa.Field(coerce=True)
    timestamp: Series[int] = pa.Field(ge=0)
    queue_imbalance: Series[float] = pa.Field(ge=-1, le=1)
    order_flow_imbalance: Series[float] = pa.Field(ge=-1, le=1)
    depth_slope_bids: Series[float] = pa.Field()  # Can be any float
    depth_slope_asks: Series[float] = pa.Field()  # Can be any float
    
    class Config:
        strict = True
        coerce = True

    @pa.check("symbol")
    def check_symbol_format(cls, series: Series[str]) -> bool:
        """Check if symbol follows expected format."""
        return series.str.contains(r'^[A-Z]+_[A-Z]+(_PERP)?$').all()

    @pa.check("timestamp")
    def check_timestamp_range(cls, series: Series[int]) -> bool:
        """Check if timestamp is within reasonable range."""
        current_time = pd.Timestamp.now().timestamp() * 1e6  # microseconds
        return (series >= 0) & (series <= current_time).all()

    @pa.check("depth_slope_bids")
    def check_depth_slope_bids(cls, series: Series[float]) -> bool:
        """Check if bid slope is negative (decreasing prices)."""
        return (series <= 0).all()

    @pa.check("depth_slope_asks")
    def check_depth_slope_asks(cls, series: Series[float]) -> bool:
        """Check if ask slope is positive (increasing prices)."""
        return (series >= 0).all()

# Example usage:
# df = pd.DataFrame({...})
# validated_df = L2FeaturesSchema.validate(df) 