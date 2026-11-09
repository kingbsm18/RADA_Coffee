import { redirect } from "next/navigation";

/** Default authenticated landing page: Live Operations. */
export default function Home() {
  redirect("/live");
}
