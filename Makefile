.PHONY: update run runm

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
	python main.py --atrad-fetch --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/atrad_user1.json users/atrad_user2.json --log-level DEBUG

runam:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user5.json users/user6.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

runa-no-icarus:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

runa-no-icarus56:
	python main.py --user-config users/atrad_user1.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user6.json users/user7.json users/user8.json users/user9.json --log-level DEBUG

token:
	python token_fetcher/fetch_tokens.py --all