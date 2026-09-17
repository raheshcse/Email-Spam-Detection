// Sample messages users can click to try the classifier.
// Wording is in the style of the SMS Spam Collection dataset the model was
// trained on, so the predictions are representative.

export const EXAMPLE_MESSAGES = [
  {
    id: 'prize',
    label: 'Prize scam',
    expected: 'spam',
    preview: 'You have won a $900 prize reward…',
    text: "WINNER!! You have been specially selected to receive a $900 prize reward! To claim call 09061701461 now. Claim code KL341. Valid 12 hours only.",
  },
  {
    id: 'free-offer',
    label: 'Free offer',
    expected: 'spam',
    preview: 'FREE ringtones + entry to win £1000…',
    text: "URGENT! Your mobile number has won a FREE entry into our £1000 weekly draw. Text WIN to 80086 to claim your free ringtones and cash prize now. T&C apply, 18+ only.",
  },
  {
    id: 'meeting',
    label: 'Work message',
    expected: 'ham',
    preview: 'Are we still on for the 3pm review?',
    text: "Hi Priya, are we still on for the 3pm design review? I've pushed the updated slides to the shared drive, let me know if anything looks off before the call.",
  },
  {
    id: 'personal',
    label: 'Personal note',
    expected: 'ham',
    preview: 'Running about ten minutes late…',
    text: "Hey, running about ten minutes late, traffic near the station is bad. Order the usual for me if the kitchen closes soon. See you in a bit!",
  },
]
