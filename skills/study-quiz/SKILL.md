---
name: study-quiz
description: Quiz the user on their study notes, one question at a time, and keep score. Use when the user asks to be quizzed or tested, or wants practice questions on their notes.
---

# Study quiz

## Setup

1. Use list_files and read_file to find the notes. Only use search_files if there are many files and you can't tell which one covers the topic.
2. If the user hasn't said how many questions they want, ask. Default to 5.
3. Before writing the first question, read question_styles.md with
   load_skill(name="study-quiz", file="question_styles.md").

## Running the quiz

- Ask ONE question, then stop and wait for the answer. Never list several
  questions at once.
- Base every question on something actually in the notes. Rotate through the
  styles in question_styles.md.
- After each answer:
  - say whether it's right or partly right
  - explain in one sentence, quoting the notes
  - show the running score, e.g. "Score: 2/3"

## Finishing

Give the final score, then list the topics the user missed so they know what
to review.
