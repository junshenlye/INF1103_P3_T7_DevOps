# INF1103_P3_T7_DevOps

1. Problem Statement and Target Users
o What real world problem does your application aim to solve?

Students often struggle to manage multiple assignments, quizzes, and exams across different modules, especially when deadlines overlap. Our application provides a consolidated academic schedule and helps students prioritize tasks based on deadlines and assessment weightage, allowing them to make better trade-offs between competing academic commitments. 

o Who are the intended users of the application?

SIT students managing multiple modules and graded assessments.

2. User Inputs
o What information or data will users provide to the system?
Users provide:

Assessment details: module, assessment type, weightage, and deadline.
Study preferences: personalized rules for prioritization, such as additional revision time before quizzes or buffer periods before final exams.

These inputs allow the system to generate a priority timeline tailored to each student’s workload and study habits.

3. Use of AI
o How will AI be utilized within the application?

A multimodal AI model will extract assessment information from uploaded module schedules and combine it with the user's study preferences. The model will evaluate competing assessments based on factors such as deadline, weightage, and required preparation time to determine their relative priority.

o What outputs, insights, or recommendations will the AI generate from the user inputs?

The AI will generate a rolling priority timeline containing upcoming assessments and recommended preparation periods.

Each event will include:

Module and assessment type
Deadline
Assessment weightage
Recommended preparation period
Priority level

When multiple assessments occur within the same period, they will be displayed as stacked blocks to show competing workload and priority.


4. Business Rules
o What business rules, validations, or decision-making logic will be applied to the AI-generated outputs?

The AI output must follow a predefined JSON structure before it can be accepted by the application.

Each timeline block must contain required fields such as:

Module
Assessment category
Deadline
Weightage
Priority
Start and end period
Block size

The application will validate that:

Required fields are present.
Dates and weightages are valid.
Events are positioned in the correct week.
Higher-weighted or more urgent assessments receive appropriate priority.
Timeline blocks follow the required category and size format.

Invalid AI outputs will be rejected and regenerated before being displayed to the user.

Git Repository:
https://github.com/junshenlye/INF1103_P3_T7_DevOps 

