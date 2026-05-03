import { redirect } from "next/navigation";

import { LoginForm } from "../../components/login-form";
import { getSession } from "../../lib/api";

export default async function LoginPage() {
  const session = await getSession();
  if (session.authenticated) {
    redirect("/dashboard");
  }
  return <LoginForm />;
}
