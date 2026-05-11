PROFILE ?= dbc-de54b796-a6c4
TF_EXEC_PATH ?= /usr/local/bin/terraform
TF_VERSION ?= 1.5.7

.PHONY: validate deploy app-deploy

validate:
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks bundle validate --profile $(PROFILE)

deploy:
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks bundle deploy --profile $(PROFILE)
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks apps deploy --profile $(PROFILE)

app-deploy:
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks apps deploy --profile $(PROFILE)
