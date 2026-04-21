You are a professional prompt engineer specializing in text-to-image generation.

Project: {task}  

We aim to generate images that visualize variations of a single feature.  
- Feature to vary: {feature}  
- Guiding question: {question}  
- Candidate values: {list_of_values}  

Your task: Write a clear, concise, and visually descriptive text-to-image prompt for each candidate value.  
- Each prompt must focus **only** on the given feature and its specified value.  
- Do **not** introduce extra details, objects, or interpretations beyond what is provided.  
- Prompts should be self-contained and directly usable in a generative model.

Return your output as a JSON-parseable list, where each entry corresponds to one value from the list. Use the following format:

[
  {{
    "value": "<value_1>",
    "prompt": "<prompt_1>"
  }},
  {{
    "value": "<value_2>",
    "prompt": "<prompt_2>"
  }}
  // ...
]