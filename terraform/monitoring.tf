# ==============================================================================
# Virtusa Project TicketDesk - CloudWatch Monitoring & Observability (Phase 8)
# ==============================================================================
# This configuration provisions cost-conscious observability for the TicketDesk
# Phase 7 AWS Lambda attachment processor.
#
# ARCHITECTURAL & COST CONSIDERATIONS:
# 1. Bounded Log Retention: By default, CloudWatch retains log streams indefinitely
#    ('Never Expire'), accumulating hidden storage charges. We explicitly manage
#    the log group with a 7-day retention period, keeping storage within the AWS
#    Free Tier (5 GB free ingestion/storage).
# 2. Minimal Alarms (Free-Tier Compliant): AWS Free Tier includes 10 free standard
#    CloudWatch metric alarms per month ($0.10/alarm/month thereafter). We provision
#    exactly 2 alarms (Errors and Throttles), costing $0.00.
# 3. No Unnecessary Dashboards: CloudWatch Dashboards cost $3.00/month after the
#    first 3 free dashboards. We intentionally omit a Terraform-managed dashboard
#    to keep POC operational costs at absolute zero ($0.00).
# ==============================================================================

# ------------------------------------------------------------------------------
# 1. CloudWatch Log Group (7-Day Retention for POC Cost Control)
# ------------------------------------------------------------------------------
# Pre-creates the Lambda log group with an explicit 7-day retention policy.
# When Lambda executes, it inherits this configuration automatically.
resource "aws_cloudwatch_log_group" "lambda_log_group" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-attachment-processor"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-log-group"
    Purpose     = "TicketDesk Lambda Execution Logs"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# 2. CloudWatch Alarm: Lambda Invocation Errors (Priority Alarm)
# ------------------------------------------------------------------------------
# Triggers if the Lambda function encounters 1 or more runtime exceptions or
# unhandled invocation errors within a 5-minute evaluation period.
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.project_name}-${var.environment}-lambda-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300 # 5-minute evaluation window
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Triggers when TicketDesk Lambda attachment processor records 1 or more invocation errors in 5 minutes"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "${var.project_name}-${var.environment}-attachment-processor"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-errors-alarm"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# 3. CloudWatch Alarm: Lambda Execution Throttles (Secondary Alarm)
# ------------------------------------------------------------------------------
# Triggers if Lambda invocations are throttled due to regional account limits or
# concurrency exhaustion (Throttles >= 1 within a 5-minute evaluation period).
resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  alarm_name          = "${var.project_name}-${var.environment}-lambda-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300 # 5-minute evaluation window
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Triggers when TicketDesk Lambda attachment processor encounters execution throttling"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = "${var.project_name}-${var.environment}-attachment-processor"
  }

  tags = {
    Name        = "${var.project_name}-${var.environment}-lambda-throttles-alarm"
    Environment = var.environment
  }
}

# ------------------------------------------------------------------------------
# 4. Outputs: Phase 8 Observability Resources
# ------------------------------------------------------------------------------
output "cloudwatch_log_group_name" {
  description = "The name of the CloudWatch Log Group with 7-day retention"
  value       = aws_cloudwatch_log_group.lambda_log_group.name
}

output "cloudwatch_alarm_lambda_errors_arn" {
  description = "The ARN of the CloudWatch Alarm monitoring Lambda invocation errors"
  value       = aws_cloudwatch_metric_alarm.lambda_errors.arn
}

output "cloudwatch_alarm_lambda_throttles_arn" {
  description = "The ARN of the CloudWatch Alarm monitoring Lambda throttling"
  value       = aws_cloudwatch_metric_alarm.lambda_throttles.arn
}
