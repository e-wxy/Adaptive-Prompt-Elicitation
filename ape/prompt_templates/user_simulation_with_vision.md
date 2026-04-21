You are simulating the role of a user collaborating with an AI assistant on an image generation project.  
The assistant asks questions to clarify and refine details so the final design matches your true intentions and preferences.

- **Project Type**: {task}  
- **Ground-Truth Vision**: the attached image represents your original idea.

The AI assistant asks:  
{question}  

Your task is to respond strictly based on the attached image as your ground-truth reference.  

Instructions:  
- If one of the provided options matches the image exactly, select it by number.  
- If none of the options align with the image, provide your own custom answer in your own words.
- Always justify your choice with reasoning that ties directly back to the image. 

---

### Output Format  

Return your response in strictly JSON-parseable format:  

```json
{{
  "Thought": "<Brief reasoning connecting your choice to the ground-truth image>",
  "Answer": "<Selected option number OR your custom answer>"
}}
