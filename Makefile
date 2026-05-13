PROFILE ?= dbc-de54b796-a6c4
TF_EXEC_PATH ?= /usr/local/bin/terraform
TF_VERSION ?= 1.5.7
PYTHON ?= python
APP_NAME ?= bertopic-narrative-analysis
GENIE_SPACE_ID ?= 01f14d5383a21f0e8626a80d72315de3
GENIE_PAYLOAD ?= genie_space/bertopic_narrative_space.json
WAREHOUSE_ID ?= 593af0ca865fa166
WAREHOUSE_NAME ?= Serverless Starter Warehouse
WAREHOUSE_CLUSTER_SIZE ?= 2X-Small
WAREHOUSE_MIN_CLUSTERS ?= 1
WAREHOUSE_MAX_CLUSTERS ?= 1
WAREHOUSE_AUTO_STOP_MINS ?= 10

.PHONY: status diff check py-check genie-payload-check validate bundle-deploy deploy app-deploy genie-deploy genie-get app-get warehouse-list warehouse-get warehouse-disable-serverless

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
	$(PYTHON) scripts/deploy_genie_space.py --profile $(PROFILE) --warehouse-id $(WAREHOUSE_ID)

genie-get:
	databricks genie get-space $(GENIE_SPACE_ID) \
		--include-serialized-space \
		--profile $(PROFILE) \
		--output json

app-get:
	databricks apps get $(APP_NAME) \
		--profile $(PROFILE) \
		--output json

warehouse-list:
	databricks warehouses list \
		--profile $(PROFILE) \
		--output json

warehouse-get:
	databricks warehouses get $(WAREHOUSE_ID) \
		--profile $(PROFILE) \
		--output json

warehouse-disable-serverless:
	databricks warehouses edit $(WAREHOUSE_ID) \
		--profile $(PROFILE) \
		--no-wait \
		--json '{"name":"$(WAREHOUSE_NAME)","cluster_size":"$(WAREHOUSE_CLUSTER_SIZE)","min_num_clusters":$(WAREHOUSE_MIN_CLUSTERS),"max_num_clusters":$(WAREHOUSE_MAX_CLUSTERS),"auto_stop_mins":$(WAREHOUSE_AUTO_STOP_MINS),"enable_photon":true,"enable_serverless_compute":false,"warehouse_type":"PRO","spot_instance_policy":"COST_OPTIMIZED"}'
