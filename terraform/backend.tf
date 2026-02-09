terraform {
  backend "s3" {
    bucket  = "closernotes-terraform-state"
    key     = "closernotes/terraform.tfstate"
    region  = "us-west-2"
    encrypt = true
  }
}
