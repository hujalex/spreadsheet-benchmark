Task 1
The task was designed to evaluate whether or not the model would be able to perform
a merge across multiple files. We would evaluate the result deterministically against
a standard Pandas merge. Since the llm, cannot output dataframes, we had the llm instead output a JSON object and we would convert the ground truth dataframe into a JSON object as well for comparison.




Task 2



Task 3


Agent
Developed with tinker from Thinking Machines Lab. Designed with reinforcement learning with the idea that the model would improve results after every single training iteration, and we would be able to witness the failures that the model encounters at every step as it attempts to learn in the face of the given tasks. 
After each learning step, we would 