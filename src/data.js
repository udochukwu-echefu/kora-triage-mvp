export const customers = {
  "CUS-1042": {
    name: "Chidinma Okeke",
    phone: "+234 803 ••• 4412",
    tier: "Business",
    since: "March 2024",
    notes: ["Preferred channel: WhatsApp", "Previously reported a delayed transfer", "Identity verified 08 Jul"],
    previousContext: "Transfer TRX-920184 for ₦82,500 was pending. Customer already supplied the transaction ID and recipient bank."
  },
  "CUS-2048": {
    name: "Tunde Adebayo",
    phone: "+234 706 ••• 1139",
    tier: "Standard",
    since: "January 2025",
    notes: ["Preferred channel: Email", "One resolved card dispute"],
    previousContext: "Card ending 7721 was debited twice on 29 June. One debit was reversed."
  },
  "CUS-3071": {
    name: "Amina Bello",
    phone: "+234 812 ••• 0883",
    tier: "Standard",
    since: "September 2024",
    notes: ["Preferred language: English", "Delivery address in Kaduna"],
    previousContext: "Order ORD-44890 was expected in Kaduna on 10 July."
  },
  "CUS-4096": {
    name: "Emeka Nwosu",
    phone: "+234 809 ••• 5620",
    tier: "Business",
    since: "May 2023",
    notes: ["High-value merchant", "Callback consent on file", "KYC reviewed 04 Jul"],
    previousContext: "Account access was restored after a device change. Customer has already completed identity verification."
  },
  "CUS-5120": {
    name: "Blessing Eze",
    phone: "+234 815 ••• 9034",
    tier: "Standard",
    since: "February 2025",
    notes: ["Preferred language: Pidgin", "No prior escalations"],
    previousContext: "First payment complaint. No open cases."
  },
  "CUS-6113": {
    name: "Seyi Balogun",
    phone: "+234 802 ••• 7701",
    tier: "Standard",
    since: "August 2024",
    notes: ["Preferred channel: WhatsApp", "Two completed deliveries"],
    previousContext: "Order ORD-77401 was marked delivered, but customer says it was not received."
  },
  "CUS-7188": {
    name: "Fatima Lawal",
    phone: "+234 816 ••• 2860",
    tier: "Standard",
    since: "April 2025",
    notes: ["Accessibility: prefers written instructions", "Identity not yet reverified"],
    previousContext: "Password reset link expired twice. No account details should be changed until reverified."
  },
  "CUS-8234": {
    name: "Ifeanyi Obi",
    phone: "+234 705 ••• 4198",
    tier: "Business",
    since: "November 2023",
    notes: ["Frequent transfers", "Previous fraud false positive"],
    previousContext: "Customer recognises all recent transfers except the new debit reported today."
  }
};

export const messages = [
  {
    id: "KOR-2401", customerId: "CUS-1042", channel: "whatsapp", receivedAt: "10:42", minutesAgo: 4,
    message: "Abeg this transfer still dey pending since morning. I don send the transaction ID before, na TRX-920184. ₦82,500 no reach the person and una don debit me.",
    truthIntent: "Transfer pending", truthUrgency: "high"
  },
  {
    id: "KOR-2402", customerId: "CUS-3071", channel: "email", receivedAt: "10:38", minutesAgo: 8,
    subject: "Order still not delivered",
    message: "Hello, my order ORD-44890 was meant to arrive on Thursday in Kaduna. The tracking has not changed for three days. Please advise.",
    truthIntent: "Delivery delayed", truthUrgency: "medium"
  },
  {
    id: "KOR-2403", customerId: "CUS-8234", channel: "whatsapp", receivedAt: "10:31", minutesAgo: 15,
    message: "I DID NOT MAKE THIS ₦145,000 DEBIT! If my money disappears you people will hear from me today. Account 0192846671. Block everything now.",
    truthIntent: "Fraud report", truthUrgency: "critical"
  },
  {
    id: "KOR-2404", customerId: "CUS-2048", channel: "email", receivedAt: "10:20", minutesAgo: 26,
    subject: "Duplicate card debit",
    message: "My card ending 7721 was charged twice again for ₦18,400 at Market Square. Kindly reverse the duplicate transaction.",
    truthIntent: "Duplicate debit", truthUrgency: "high"
  },
  {
    id: "KOR-2405", customerId: "CUS-5120", channel: "whatsapp", receivedAt: "10:12", minutesAgo: 34,
    message: "I try pay ₦7,250 for light bill, e fail but una remove money. Wetin I go do? Ref PAY-551902.",
    truthIntent: "Payment failed", truthUrgency: "medium"
  },
  {
    id: "KOR-2406", customerId: "CUS-4096", channel: "email", receivedAt: "09:58", minutesAgo: 48,
    subject: "Locked out after phone change",
    message: "I changed my phone yesterday and cannot access the business account. I already completed verification last week. Please do not ask me to upload the same documents again.",
    truthIntent: "Account access", truthUrgency: "high"
  },
  {
    id: "KOR-2407", customerId: "CUS-6113", channel: "whatsapp", receivedAt: "09:41", minutesAgo: 65,
    message: "Your app says delivered but I no see anything. Order ORD-77401. Rider no call me and nobody for my house collect am.",
    truthIntent: "Delivery missing", truthUrgency: "high"
  },
  {
    id: "KOR-2408", customerId: "CUS-7188", channel: "email", receivedAt: "09:27", minutesAgo: 79,
    subject: "Reset link keeps expiring",
    message: "The password reset link has expired for the third time. I need access today to download my statement for an application.",
    truthIntent: "Account access", truthUrgency: "medium"
  },
  {
    id: "KOR-2409", customerId: "CUS-1042", channel: "whatsapp", receivedAt: "09:02", minutesAgo: 104,
    message: "Una said wait 30 minutes yesterday but nothing happen. Same transfer issue. I no fit keep explaining myself every time.",
    truthIntent: "Transfer pending", truthUrgency: "high"
  },
  {
    id: "KOR-2410", customerId: "CUS-3071", channel: "email", receivedAt: "08:44", minutesAgo: 122,
    subject: "Change delivery address",
    message: "Can you redirect my package to Abuja instead? I will not be in Kaduna this week. It is the same order I emailed about earlier.",
    truthIntent: "Delivery change", truthUrgency: "medium"
  },
  {
    id: "KOR-2411", customerId: "CUS-5120", channel: "whatsapp", receivedAt: "08:16", minutesAgo: 150,
    message: "How long e dey take to verify account? I submit everything on Friday.",
    truthIntent: "Account verification", truthUrgency: "low"
  },
  {
    id: "KOR-2412", customerId: "CUS-2048", channel: "email", receivedAt: "07:52", minutesAgo: 174,
    subject: "Refund timeline",
    message: "Good morning. The merchant confirmed a refund of NGN 12,000 on 8 July. When should it reflect in my balance?",
    truthIntent: "Refund pending", truthUrgency: "low"
  }
];
