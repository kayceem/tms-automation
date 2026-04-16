.PHONY: update run runm runaf prepare tui

Arguments := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

update:
	python utils/update_user_tokens.py --auto users

run:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json --log-level DEBUG

runm:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json users/user5.json users/user6.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

run-no-icarus:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

sell:
	python main.py --user-config users/user1.json --order-store stores/sell_store.json --fetch-user users/user2.json --log-level DEBUG

runa:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json --log-level DEBUG

runaf:
	python main.py --atrad-fetch --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/atrad_user2.json users/atrad_user3.json users/atrad_user4.json users/atrad_user5.json users/atrad_user6.json users/atrad_user7.json $(if $(LOG),--log-level $(LOG)) $(if $(TIME),--time $(TIME))

runaf-sell:
	python main.py --atrad-fetch --user-config users/atrad_user1.json --order-store stores/sell_store.json --fetch-users users/atrad_user2.json users/atrad_user3.json users/atrad_user4.json users/atrad_user5.json users/atrad_user6.json users/atrad_user7.json --log-level DEBUG

runam:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user5.json users/user6.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

runa-no-icarus:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

runa-no-icarus56:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user6.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

token:
	python token_fetcher/fetch_tokens.py --all

reset-tokens:
	python utils/config/update_atrad.py --reset

set-values:
	python utils/config/update_atrad.py --set $(Arguments)

update-store:
	python utils/config/update_order_prices.py --atrad-user users/atrad_user6.json --order-store stores/order_store.json

prepare:
	$(MAKE) reset-tokens
	$(MAKE) update-store

tui:
	python -m tui

%:
	@:
