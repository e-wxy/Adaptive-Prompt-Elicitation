- Project: {design_type}
- User Description: {user_input}

Your task is to carefully analyze the user’s description and extract explicit visual requirements relevant to the specified design type.

Guidelines for analysis:
	•	Identify features mentioned in the user’s input and phrase them professionally.
    •   Structure subfeatures logically when appropriate.
	•	If no clear requirements are identifiable, return an empty dictionary.

⸻

Output Format

Return your response in strictly JSON-parseable format with the following structure:

{{
  "Thought": "<concise reasoning about how you derived the requirements>",
  "Requirements": {{
    "<Feature Name 1>": "<value>",
    "<Feature Name 2>": {{
      "<Subfeature A>": "<value>",
      "<Subfeature B>": {{
        "<Subsubfeature a>": "<value>",
        // ...
      }}
    // ...
    }}
  }}
}}