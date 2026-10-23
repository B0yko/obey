import pandas as pd


def clean(df: pd.DataFrame) -> pd.DataFrame:
    return df.dropna()
