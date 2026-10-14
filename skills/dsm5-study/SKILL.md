---
name: dsm5-study
description: Quiz the user on DSM-5-TR disorders by giving key symptoms and asking them to name the disorder, and explain the differences between similar disorders. Use when the user wants to study, practice, or be quizzed on DSM-5 diagnoses, or asks how two disorders differ.
---

# DSM-5 study

## Quiz mode
1. Read disorders.json with load_skill(name="dsm5-study", file="disorders.json").
2. If the user named a category (e.g. personality disorders), quiz only those.
3. Show ONE disorder's symptoms and ask the user to name it. Wait for the answer.
4. Grading:
   - Accept abbreviations and common variants ("OCD", "bipolar 1", "ADHD").
   - If the answer is the right family but not specific enough (e.g.
     "delusional disorder" for jealous delusional disorder), give half
     credit and name the specific type.
   - If wrong, give the answer AND the one symptom that best separates it
     from what the user guessed.
5. Show the running score after each question.

## Comparison mode
When asked how two disorders differ, compare them using their entries in
disorders.json. Focus on what tells them apart: duration, age of onset,
or a required symptom.

Base answers on disorders.json, not general knowledge. If a disorder isn't
in the file, say so.