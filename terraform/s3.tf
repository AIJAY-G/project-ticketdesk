# ==============================================================================
# Amazon S3 Bucket - TicketDesk Ticket Attachments
# ==============================================================================
resource "aws_s3_bucket" "attachments" {
  bucket_prefix = "${var.project_name}-${var.environment}-attachments-"
  force_destroy = false

  tags = {
    Name        = "${var.project_name}-${var.environment}-attachments"
    Purpose     = "Ticket Attachments Storage"
    Environment = var.environment
  }
}

# ==============================================================================
# S3 Block Public Access (All 4 Controls Enabled)
# ==============================================================================
resource "aws_s3_bucket_public_access_block" "attachments" {
  bucket = aws_s3_bucket.attachments.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ==============================================================================
# S3 Bucket Versioning (Preserves Object History & Prevents Accidental Overwrites)
# ==============================================================================
resource "aws_s3_bucket_versioning" "attachments" {
  bucket = aws_s3_bucket.attachments.id

  versioning_configuration {
    status = "Enabled"
  }
}

# ==============================================================================
# S3 Server-Side Encryption (SSE-S3 / AES256)
# ==============================================================================
resource "aws_s3_bucket_server_side_encryption_configuration" "attachments" {
  bucket = aws_s3_bucket.attachments.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

