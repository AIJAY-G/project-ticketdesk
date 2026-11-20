# ==============================================================================
# Virtusa Project TicketDesk - AWS Lambda Attachment Processor (Phase 7)
# ==============================================================================
# This configuration deploys the serverless attachment processing function and
# attaches an event-driven trigger from the TicketDesk Amazon S3 bucket.
#
# ARCHITECTURAL DESIGN & COST-CONSCIOUS CHOICES:
# 1. Serverless Compute: AWS Lambda running Python 3.12 runtime.
# 2. Outside VPC: Lambda is deliberately deployed outside the VPC to access S3
#    and CloudWatch via standard AWS API endpoints at $0.00 network cost, completely
#    avoiding expensive NAT Gateways (~$32.40/month) or VPC endpoints.
# 3. Dedicated IAM Role: Creates a standalone execution role with least-privilege
#    permissions strictly scoped to Lambda logging and read-only S3 attachment access.
#    The EC2 IAM role is untouched.
# 4. S3 Bucket Notification: Coordinates with Vasantha's 'aws_s3_bucket.attachments'
#    resource to listen for 's3:ObjectCreated:*' events under 'attachments/'.
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. Lambda Code Packaging
# ------------------------------------------------------------------------------
# Automatically packages the Python Lambda handler into a zip archive during deployment
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambda/attachment_processor.py"
  output_path = "${path.module}/attachment_processor.zip"
}

# ------------------------------------------------------------------------------
# 2. Dedicated IAM Execution Role (Least Privilege)
# ------------------------------------------------------------------------------
resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_name}-${var.environment}-lambda-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "LambdaAssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-exec-role"
    Purpose     = "Execution role for TicketDesk S3 attachment processor Lambda"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# 3. Least-Privilege IAM Policy for Lambda
# ------------------------------------------------------------------------------
# Grants least-privilege CloudWatch logging permissions strictly restricted to
# this Lambda function's log group. S3 read permissions (s3:GetObject) are
# intentionally excluded because the handler extracts all object metadata directly
# from the incoming S3 event notification payload without calling S3 GET APIs.
resource "aws_iam_policy" "lambda_policy" {
  name        = "${var.project_name}-${var.environment}-lambda-policy"
  description = "Grants least-privilege CloudWatch logging for TicketDesk attachment processor Lambda"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchLogging"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/lambda/${var.project_name}-${var.environment}-attachment-processor:*"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-policy"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "lambda_policy_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_policy.arn
}

# ------------------------------------------------------------------------------
# 4. AWS Lambda Function
# ------------------------------------------------------------------------------
resource "aws_lambda_function" "attachment_processor" {
  function_name = "${var.project_name}-${var.environment}-attachment-processor"
  description   = "Processes uploaded ticket attachments, extracts metadata, and logs to CloudWatch"
  role          = aws_iam_role.lambda_exec.arn
  handler       = "attachment_processor.lambda_handler"
  runtime       = "python3.12"

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  # Cost-conscious configuration (Free-Tier eligible)
  memory_size = 128
  timeout     = 15

  # Non-VPC deployment for zero infrastructure cost
  # No vpc_config block is specified intentionally

  environment {
    variables = {
      # Optional SNS Topic ARN (empty by default to avoid charges)
      SNS_TOPIC_ARN = ""
      ENVIRONMENT   = var.environment
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-attachment-processor"
    Purpose     = "TicketDesk S3 Attachment Processing"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# 5. Lambda Permission for Amazon S3 Trigger
# ------------------------------------------------------------------------------
# Explicitly grants Amazon S3 service principal permission to invoke this Lambda
resource "aws_lambda_permission" "allow_s3_invocation" {
  statement_id  = "AllowExecutionFromS3Bucket"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.attachment_processor.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.attachments.arn
}

# ------------------------------------------------------------------------------
# 6. Amazon S3 Bucket Notification Trigger
# ------------------------------------------------------------------------------
# Configures the S3 bucket to trigger Lambda only when new objects land under 'attachments/'
resource "aws_s3_bucket_notification" "attachment_trigger" {
  bucket = aws_s3_bucket.attachments.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.attachment_processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "attachments/"
  }

  depends_on = [aws_lambda_permission.allow_s3_invocation]
}

# ------------------------------------------------------------------------------
# 7. Outputs: Phase 7 Lambda Integration
# ------------------------------------------------------------------------------
output "lambda_function_name" {
  description = "The name of the TicketDesk attachment processor Lambda function"
  value       = aws_lambda_function.attachment_processor.function_name
}

output "lambda_function_arn" {
  description = "The ARN of the TicketDesk attachment processor Lambda function"
  value       = aws_lambda_function.attachment_processor.arn
}

output "lambda_execution_role_arn" {
  description = "The ARN of the dedicated IAM execution role for the Lambda function"
  value       = aws_iam_role.lambda_exec.arn
}
