"""Explicit, exhaustive permissions; unknown tools fail closed."""

READ_TOOLS = {
    "banking": {
        "get_iban", "get_balance", "get_most_recent_transactions",
        "get_scheduled_transactions", "read_file", "get_user_info",
    },
    "slack": {
        "get_channels", "read_channel_messages", "read_inbox",
        "get_users_in_channel", "get_webpage",
    },
    "travel": {
        "get_user_information", "get_all_hotels_in_city", "get_hotels_prices",
        "get_rating_reviews_for_hotels", "get_hotels_address",
        "get_all_restaurants_in_city", "get_cuisine_type_for_restaurants",
        "get_restaurants_address", "get_rating_reviews_for_restaurants",
        "get_dietary_restrictions_for_all_restaurants",
        "get_contact_information_for_restaurants", "get_price_for_restaurants",
        "check_restaurant_opening_hours", "get_all_car_rental_companies_in_city",
        "get_car_types_available", "get_rating_reviews_for_car_rental",
        "get_car_fuel_options", "get_car_rental_address", "get_car_price_per_day",
        "get_flight_information", "search_calendar_events", "get_day_calendar_events",
    },
    "workspace": {
        "get_unread_emails", "get_sent_emails", "get_received_emails",
        "get_draft_emails", "search_emails", "search_contacts_by_name",
        "search_contacts_by_email", "get_current_day", "search_calendar_events",
        "get_day_calendar_events", "search_files_by_filename", "get_file_by_id",
        "list_files", "search_files",
    },
}

WRITE_TOOLS = {
    "banking": {"send_money", "schedule_transaction", "update_scheduled_transaction",
                "update_password", "update_user_info"},
    "slack": {"add_user_to_channel", "send_direct_message", "send_channel_message",
              "invite_user_to_slack", "remove_user_from_slack", "post_webpage"},
    "travel": {"create_calendar_event", "cancel_calendar_event", "reserve_hotel",
               "reserve_car_rental", "reserve_restaurant", "send_email"},
    "workspace": {"send_email", "delete_email", "create_calendar_event",
                  "cancel_calendar_event", "reschedule_calendar_event",
                  "add_calendar_event_participants", "append_to_file", "create_file",
                  "delete_file", "share_file"},
}


class Permissions:
    def __init__(self, suite_name, tool_names):
        self.allowed = {"A": READ_TOOLS[suite_name], "B": WRITE_TOOLS[suite_name]}
        known = self.allowed["A"] | self.allowed["B"]
        actual = set(tool_names)
        if known != actual or self.allowed["A"] & self.allowed["B"]:
            raise ValueError(f"Permission coverage mismatch: unknown={actual-known}, stale={known-actual}")

    def check(self, actor, name):
        if name not in self.allowed.get(actor, set()):
            raise PermissionError(f"DENIED: Agent {actor} may not execute {name}")
