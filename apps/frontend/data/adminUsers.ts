export type UserSummary = {
  id: string;
  name: string;
  email: string;
  title: string;
  status: "active" | "invited";
  lastActive: string;
};

export const STAFF_USERS: UserSummary[] = [
  {
    id: "staff-1",
    name: "Meera Khan",
    email: "meera.khan@acme.com",
    title: "Portfolio Strategist",
    status: "active",
    lastActive: "Active now",
  },
  {
    id: "staff-2",
    name: "Rahul Menon",
    email: "rahul.menon@acme.com",
    title: "Risk Analyst",
    status: "active",
    lastActive: "Active 8m ago",
  },
  {
    id: "staff-3",
    name: "Sahana Iyer",
    email: "sahana.iyer@acme.com",
    title: "Customer Success",
    status: "invited",
    lastActive: "Invitation sent",
  },
  {
    id: "staff-4",
    name: "Kartik Rao",
    email: "kartik.rao@acme.com",
    title: "Compliance Lead",
    status: "active",
    lastActive: "Active 2h ago",
  },
];

export const CUSTOMER_USERS: UserSummary[] = [
  {
    id: "customer-1",
    name: "Neha Sharma",
    email: "neha.sharma@example.com",
    title: "Ultra HNI",
    status: "active",
    lastActive: "Traded 5m ago",
  },
  {
    id: "customer-2",
    name: "Ajay Kapoor",
    email: "ajay.kapoor@example.com",
    title: "Premium",
    status: "active",
    lastActive: "Reviewed 42m ago",
  },
  {
    id: "customer-3",
    name: "Ishita Paul",
    email: "ishita.paul@example.com",
    title: "Standard",
    status: "invited",
    lastActive: "Invitation sent",
  },
  {
    id: "customer-4",
    name: "Rohan Batra",
    email: "rohan.batra@example.com",
    title: "Premium",
    status: "active",
    lastActive: "Checked in 1d ago",
  },
];

