Task 1
The task was designed to evaluate whether or not the model would be able to perform
a merge across multiple files. We would evaluate the result deterministically against
a standard Pandas merge. Since the llm, cannot output dataframes, we had the llm instead output a JSON object and we would convert the ground truth dataframe into a JSON object as well for comparison.


Task 2
Designed this task to evaluate an agent's capabilities to perform a computation under 


Task 3


Agent
Developed with tinker from Thinking Machines Lab. Designed with reinforcement learning with the idea that the model would improve results after every single training iteration, and we would be able to witness the failures that the model encounters at every step as it attempts to learn in the face of the given tasks. 
Each learning step consisted of 5 scenarios for each of the 3 different tasks. For each of the 5 scenarios, the model would output 8 different responses each graded individually. 

- 10 learning steps in total
- 8 groupsize (responses the model generates)
- 5 scenarios per task
- 3 different tasks (merge, policy, memo)
