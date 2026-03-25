.PHONY: update run runm

update:
	python utils/update_user_tokens.py --auto users

run:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-user users/user2.json --log-level DEBUG

runm:
	python main.py --user-config users/user1.json --order-store stores/order_store.json --fetch-users users/user2.json users/user3.json --log-level DEBUG
