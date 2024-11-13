from __future__ import unicode_literals
import frappe
from frappe import _
import requests.exceptions
from .woocommerce_requests import get_woocommerce_customers, post_request, put_request
from .utils import make_woocommerce_log

def sync_customers():
    woocommerce_customer_list = []
    sync_woocommerce_customers(woocommerce_customer_list)
    frappe.local.form_dict.count_dict["customers"] = len(woocommerce_customer_list)

def sync_woocommerce_customers(woocommerce_customer_list):
    for woocommerce_customer in get_woocommerce_customers():
        # import new customer or update existing customer
        if not frappe.db.get_value("Customer", {"woocommerce_customer_id": woocommerce_customer.get('id')}, "name"):
            #only synch customers with address
            if woocommerce_customer.get("billing").get("address_1") != "" and woocommerce_customer.get("shipping").get("address_1") != "":
                create_customer(woocommerce_customer, woocommerce_customer_list)
            # else:
            #    make_woocommerce_log(title="customer without address", status="Error", method="create_customer",
            #        message= "customer without address found",request_data=woocommerce_customer, exception=False)
        else:
            update_customer(woocommerce_customer)

def update_customer(woocommerce_customer):
    return

def create_customer(woocommerce_customer, woocommerce_customer_list):
    import frappe.utils.nestedset

    woocommerce_settings = frappe.get_doc("WooCommerce Config", "WooCommerce Config")
    
    # Construct the customer name
    cust_name = (woocommerce_customer.get("first_name") + " " + (woocommerce_customer.get("last_name") or "")) \
        if woocommerce_customer.get("first_name") else woocommerce_customer.get("email")
        
    try:
        # Try to match territory
        country_name = get_country_name(woocommerce_customer["billing"]["country"])
        if frappe.db.exists("Territory", country_name):
            territory = country_name
        else:
            territory = frappe.utils.nestedset.get_root_of("Territory")

        # Create the customer document
        customer = frappe.get_doc({
            "doctype": "Customer",
            "name": woocommerce_customer.get("id"),
            "customer_name": cust_name,
            "woocommerce_customer_id": woocommerce_customer.get("id"),
            "sync_with_woocommerce": 0,
            "customer_group": woocommerce_settings.customer_group,
            "territory": territory,
            "customer_type": _("Individual")
        })
        customer.flags.ignore_mandatory = True
        customer.insert()
        frappe.db.commit()  # Commit the transaction to save the customer

        # Log success
        frappe.logger().debug(f"Created new customer: {cust_name}")

        # Create customer address and contact
        create_customer_address(woocommerce_customer, customer.name)  # Pass customer name
        create_customer_contact(customer, woocommerce_customer)  # Assuming create_customer_contact still needs customer

        # Append the customer ID to the list
        woocommerce_customer_list.append(woocommerce_customer.get("id"))
        
        # Log success
        make_woocommerce_log(title="create customer", status="Success", method="create_customer",
            message="create customer", request_data=woocommerce_customer, exception=False)
            
    except Exception as e:
        make_woocommerce_log(title=str(e), status="Error", method="create_customer", 
            message=frappe.get_traceback(), request_data=woocommerce_customer, exception=True)
            

# State Abbreviations to Full Names Mapping
STATE_ABBR_TO_FULL_NAME = {
    "AP": "Andhra Pradesh", "AR": "Arunachal Pradesh", "AS": "Assam", "BR": "Bihar", "CT": "Chhattisgarh",
    "GA": "Goa", "GJ": "Gujarat", "HR": "Haryana", "HP": "Himachal Pradesh", "JK": "Jammu and Kashmir", 
    "KA": "Karnataka", "KL": "Kerala", "MP": "Madhya Pradesh", "MH": "Maharashtra", "MN": "Manipur",
    "ML": "Meghalaya", "MZ": "Mizoram", "NL": "Nagaland", "OR": "Odisha", "PB": "Punjab", "RJ": "Rajasthan",
    "SK": "Sikkim", "TN": "Tamil Nadu", "TS": "Telangana", "TR": "Tripura", "UP": "Uttar Pradesh", 
    "UK": "Uttarakhand", "WB": "West Bengal", "AN": "Andaman and Nicobar Islands", "LD": "Lakshadweep",
    "DN": "Dadra and Nagar Haveli", "DL": "Delhi", "JH": "Jharkhand"
}

def create_customer_address(woocommerce_customer, customer_name):
    frappe.logger().debug(f"Received WooCommerce Customer Data: {woocommerce_customer}")
    customer_email = woocommerce_customer.get("email")

    billing_address = woocommerce_customer.get("billing")
    shipping_address = woocommerce_customer.get("shipping")

    def validate_state_name(state, country):
        if country == "IN" and state:
            # Check if the state abbreviation exists in the mapping and get the full name
            full_state = STATE_ABBR_TO_FULL_NAME.get(state)
            if full_state:
                return full_state
            else:
                frappe.logger().error(f"Invalid State Abbreviation Provided: {state}")
                frappe.throw(_("Invalid state. Please select a valid state from available options"), title=_("Invalid State"))
        return state

    def create_address(address_data, address_type, state_name):
        country = get_country_name(address_data.get("country"))
        if not frappe.db.exists("Country", country):
            country = "Switzerland"

        try:
            frappe.logger().debug(f"Creating {address_type} address with state: {state_name}")

            address_doc = frappe.get_doc({
                "doctype": "Address",
                "woocommerce_address_id": address_type,
                "woocommerce_company_name": address_data.get("company") or '',
                "address_title": customer_name,
                "address_type": address_type,
                "address_line1": address_data.get("address_1") or "Address 1",
                "address_line2": address_data.get("address_2"),
                "city": address_data.get("city") or "City",
                "state": state_name,  # Now using full name directly
                "pincode": address_data.get("postcode"),
                "country": country,
                "phone": address_data.get("phone"),
                "email_id": address_data.get("email"),
                "links": [{
                    "link_doctype": "Customer",
                    "link_name": customer_name  
                }],
                "woocommerce_first_name": address_data.get("first_name"),
                "woocommerce_last_name": address_data.get("last_name")
            }).insert()

            frappe.logger().debug(f"Successfully created {address_type} address for customer: {customer_name}")
            return address_doc

        except Exception as e:
            frappe.logger().error(f"Error creating address for {address_type} - {str(e)}")
            make_woocommerce_log(title=str(e), status="Error", method="create_customer_address", 
                                 message=frappe.get_traceback(), request_data=woocommerce_customer, exception=True)

    # Handle Billing Address
    if billing_address:
        billing_state_name = validate_state_name(billing_address.get("state"), billing_address.get("country"))
        create_address(billing_address, "Billing", billing_state_name)

    # Handle Shipping Address
    if shipping_address:
        shipping_state_name = validate_state_name(shipping_address.get("state"), shipping_address.get("country"))
        create_address(shipping_address, "Shipping", shipping_state_name)
            

# TODO: email and phone into child table
def create_customer_contact(customer, woocommerce_customer):
    try:
        # Check if the customer exists before creating a contact
        customer_doc = frappe.get_doc("Customer", customer.name)

        new_contact = frappe.get_doc({
            "doctype": "Contact",
            "first_name": woocommerce_customer["billing"]["first_name"],
            "last_name": woocommerce_customer["billing"]["last_name"],
            "links": [{
                "link_doctype": "Customer",
                "link_name": customer.name
            }]
        })
        
        # Add email if it exists
        if woocommerce_customer["billing"].get("email"):
            new_contact.append("email_ids", {
                "email_id": woocommerce_customer["billing"]["email"],
                "is_primary": 1
            })
        
        # Add phone number if it exists
        if woocommerce_customer["billing"].get("phone"):
            new_contact.append("phone_nos", {
                "phone": woocommerce_customer["billing"]["phone"],
                "is_primary_phone": 1
            })

        new_contact.insert()

    except frappe.DoesNotExistError as e:
        # Handle case where the customer does not exist
        make_woocommerce_log(
            title=f"Customer {customer.name} not found.",
            status="Error",
            method="create_customer_contact",
            message=frappe.get_traceback(),
            request_data=woocommerce_customer,
            exception=True
        )
    except Exception as e:
        # General exception handling
        make_woocommerce_log(
            title=str(e),
            status="Error",
            method="create_customer_contact",
            message=frappe.get_traceback(),
            request_data=woocommerce_customer,
            exception=True
        )

def get_country_name(code):
    coutry_name = ''
    coutry_names = """SELECT `country_name` FROM `tabCountry` WHERE `code` = '{0}'""".format(code.lower())
    for _coutry_name in frappe.db.sql(coutry_names, as_dict=1):
        coutry_name = _coutry_name.country_name
    return coutry_name