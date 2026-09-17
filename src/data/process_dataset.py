import pandas as pd
from src.data.preprocess import clean_batch


def process_dataset():

    print("Script Started")

    # Load CSV using correct encoding
    df = pd.read_csv("data/raw/email_spam.csv", encoding="latin-1")

    print("Dataset Loaded")

    # Keep only the two useful columns
    df = df[["v1", "v2"]]

    # Rename them clearly for the project
    df.columns = ["label", "message"]

    # Convert messages to lowercase and remove URLs/special characters
    texts = df["message"].astype(str).str.lower()
    texts = texts.str.replace(r"http\S+", "", regex=True)
    texts = texts.str.replace(r"[^a-zA-Z ]", "", regex=True)

    # spaCy cleaning: tokenization, stop-word removal, lemmatization
    df["clean_email"] = clean_batch(texts)

    print("Cleaning Completed")

    print(df["label"].value_counts())

    # Save cleaned dataset
    df.to_csv("data/processed/cleaned_emails.csv", index=False)

    print("File Saved")

