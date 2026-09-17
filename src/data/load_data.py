import pandas as pd

def load_data(path):
    return pd.read_csv(path, encoding="latin-1")