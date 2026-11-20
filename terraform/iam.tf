# ==============================================================================
# IAM Role for EC2 Application Server
# ==============================================================================
resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-${var.environment}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "EC2AssumeRolePolicy"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-ec2-role"
    Purpose     = "EC2 IAM Role for S3 and CloudWatch Access"
    Environment = var.environment
  }
}

# ==============================================================================
# IAM Instance Profile (Allows EC2 to Assume the Role)
# ==============================================================================
resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-${var.environment}-ec2-instance-profile"
  role = aws_iam_role.ec2.name

  tags = {
    Name        = "${var.project_name}-${var.environment}-ec2-instance-profile"
    Environment = var.environment
  }
}

# ==============================================================================
# IAM Policy: Least-Privilege S3 Bucket Access
# ==============================================================================
resource "aws_iam_policy" "s3_access" {
  name        = "${var.project_name}-${var.environment}-ec2-s3-policy"
  description = "Grants least-privilege access for EC2 to manage attachments in the TicketDesk S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowBucketListing"
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.attachments.arn
        ]
      },
      {
        Sid    = "AllowObjectReadWriteDelete"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = [
          "${aws_s3_bucket.attachments.arn}/*"
        ]
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-ec2-s3-policy"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "s3_access" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.s3_access.arn
}

# ==============================================================================
# IAM Policy: Least-Privilege CloudWatch Logs Streaming
# ==============================================================================
resource "aws_iam_policy" "cloudwatch_logs" {
  name        = "${var.project_name}-${var.environment}-ec2-cw-policy"
  description = "Grants least-privilege permission for EC2 to stream TicketDesk application logs to CloudWatch"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudWatchLogStreaming"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:aws:logs:*:*:log-group:/aws/ticketdesk/*"
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.environment}-ec2-cw-policy"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "cloudwatch_logs" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.cloudwatch_logs.arn
}

# ==============================================================================
# IAM Policy Attachment: AWS Systems Manager (SSM) Session Manager
# Enables secure shell management without opening port 22 (SSH)
# ==============================================================================
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

