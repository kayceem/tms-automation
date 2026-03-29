.PHONY: update run runm

update:
	python utils/update_user_tokens.py --auto users

run:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json --log-level DEBUG

runm:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json users/user5.json --log-level DEBUG

runmu:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json users/user4.json users/user5.json users/user6.json --log-level DEBUG

sell:
	python main.py --user-config users/user1.json --order-store stores/sell_store.json --fetch-user users/user2.json --log-level DEBUG

runa:
	python main.py --user-config users/atrad_user.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json --log-level DEBUG

runma:
	python main.py --user-config users/atrad_user.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user5.json --log-level DEBUG

runmau:
	python main.py --user-config users/atrad_user.json --order-store stores/order_store.json --fetch-users users/user1.json users/user2.json users/user3.json users/user4.json users/user5.json users/user6.json --log-level DEBUG

token:
	python token_fetcher/fetch_tokens.py --all