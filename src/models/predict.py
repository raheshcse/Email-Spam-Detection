import joblib
from src.data.preprocess import clean_text

# Load the trained model and the same vectorizer used during training
model = joblib.load("models/spam_model.pkl")
vectorizer = joblib.load("models/count_vectorizer.pkl")

while True:
    email = input("\nEnter email (or type 'exit' to stop): ")

    if email.lower() == "exit":
        print("Spam detector stopped.")
        break

    # Clean the new email in the same way as training data
    cleaned_email = clean_text(email)

    # Convert cleaned text into numbers
    X = vectorizer.transform([cleaned_email])

    # Predict ham or spam
    prediction = model.predict(X)

    print("Prediction:", prediction[0])