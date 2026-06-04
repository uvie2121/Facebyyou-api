# DynamoDB tables (on-demand billing: pay-per-request, no capacity planning).

resource "aws_dynamodb_table" "users" {
  name         = local.users_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.environment == "production"
  }

  server_side_encryption {
    enabled = true
  }
}

resource "aws_dynamodb_table" "analyses" {
  name         = local.analyses_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "user_id"
  range_key    = "analysis_id"

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "analysis_id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.environment == "production"
  }

  server_side_encryption {
    enabled = true
  }
}
