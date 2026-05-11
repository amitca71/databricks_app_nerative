PROFILE ?= dbc-de54b796-a6c4
TF_EXEC_PATH ?= /usr/local/bin/terraform
TF_VERSION ?= 1.5.7
PYTHON ?= python
APP_NAME ?= bertopic-narrative-analysis
GENIE_SPACE_ID ?= 01f14d5383a21f0e8626a80d72315de3
GENIE_PAYLOAD ?= genie_space/bertopic_narrative_space.json

.PHONY: status diff check py-check genie-payload-check validate bundle-deploy deploy app-deploy genie-deploy genie-get app-get

status:
	git status --short

diff:
	git diff -- app.py databricks.yml Makefile genie_space scripts

check: py-check genie-payload-check

py-check:
	$(PYTHON) -m py_compile app.py scripts/deploy_genie_space.py

genie-payload-check:
	$(PYTHON) -m json.tool $(GENIE_PAYLOAD) >/tmp/bertopic_genie_payload_check.json

validate:
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks bundle validate --profile $(PROFILE)

bundle-deploy: check
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks bundle deploy --profile $(PROFILE)

deploy: bundle-deploy
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks apps deploy --profile $(PROFILE)

app-deploy: check
	DATABRICKS_TF_EXEC_PATH=$(TF_EXEC_PATH) \
	DATABRICKS_TF_VERSION=$(TF_VERSION) \
	databricks apps deploy --profile $(PROFILE)

genie-deploy: check
	DATABRICKS_CONFIG_PROFILE=$(PROFILE) \
	$(PYTHON) scripts/deploy_genie_space.py --profile $(PROFILE)

genie-get:
	databricks genie get-space $(GENIE_SPACE_ID) \
		--include-serialized-space \
		--profile $(PROFILE) \
		--output json

app-get:
	databricks apps get $(APP_NAME) \
		--profile $(PROFILE) \
		--output json
