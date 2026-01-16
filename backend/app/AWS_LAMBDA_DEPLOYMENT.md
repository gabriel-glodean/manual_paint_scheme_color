# AWS Lambda deployment instructions for FastAPI

1. Ensure all dependencies are in requirements.txt (including mangum).
2. Your handler is in backend/app/lambda_handler.py as `handler`.
3. Package the backend/app directory and all required logic/local modules into a deployment zip:

   backend/app/lambda_handler.py
   backend/app/main.py
   backend/app/requirements.txt
   logic/
   local/
   ...

4. Deploy to AWS Lambda using the AWS Console, AWS CLI, or a framework like Serverless or SAM.
5. Set the Lambda handler to `lambda_handler.handler`.
6. Use API Gateway to route HTTP requests to the Lambda function.

For multiple endpoints, you can use a single FastAPI app (as here) and route all API Gateway requests to it.

