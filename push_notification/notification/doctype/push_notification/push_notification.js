// Copyright (c) 2025, Techfinite Systems and contributors
// For license information, please see license.txt

frappe.ui.form.on('Push Notification', {
	refresh: function(frm) {
		frm.add_custom_button('Send', function() {
			frappe.call({
				method: 'push_notification.notification.doctype.push_notification.push_notification.enqueue_notification',
				args: {
					notification_doc_name: frm.doc.name
				},
				freeze: true,
                freeze_message: " Sending  notification...",
				callback: function(r) {
					if (!r.exc) {
						frappe.msgprint(__('Notification queued successfully!'));
					}
				}
			});
		});
	},
    send_to: function(frm) {
        if (recipient_type === "Receiver By Document Field" && !frm.doc.doctype_name) {
            frappe.throw('Please select the Doctype Name ')
        } else if (recipient_type === "Channel" && !frm.doc.channel_category) {
            frappe.throw('Please select the Channel Category ')
        }
        update_send_to_options(frm);
    },
    recipient_type: function(frm) {
        update_send_to_options(frm);
    },
    doctype_name: function(frm) {
        update_send_to_options(frm);
    },
    channel_category:function(frm){
        update_send_to_options(frm)
    }
});

function update_send_to_options(frm) {
    const recipient_type = frm.doc.recipient_type;
    if (recipient_type === "Channel") {
        if(!frm.doc.channel_category){
            frappe.throw('Please select the Channel Category ')
        }
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: frm.doc.channel_category,
                fields: ['name'],
                limit_page_length: 1000
            },
            callback: function(r) {
                if (r.message) {
                    let designations = r.message.map(row => row.name);
                    designations.push("All Users");
                    frm.fields_dict.send_to.set_data(designations);
                     frm.refresh_field("send_to");
                } else {
                    frm.fields_dict.send_to.set_data(["All Users"]);
                     frm.refresh_field("send_to");
                }
            }
        });
    } else if (recipient_type === "Receiver By Document Field") {
        if(!frm.doc.doctype_name){
            frappe.throw('Please select the Doctype Name ')
        }
        frappe.call({
            method: "push_notification.notification.doctype.push_notification.push_notification.get_doctype_fields",
            args: {
                doctype_name: frm.doc.doctype_name
            },
            callback: function(r) {
                if (r.message) {
                    frm.fields_dict.send_to.set_data(r.message);
                    frm.refresh_field("send_to");
                }
            }
        });
    } else {
        frm.fields_dict.send_to.set_data([]);
    }
}

