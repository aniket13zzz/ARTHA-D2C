// artha-v2/frontend/app/api/export/tally/route.ts
import { NextRequest, NextResponse } from "next/server";
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function GET(req: NextRequest) {
  const cookieStore = cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { get: (name: string) => cookieStore.get(name)?.value } }
  );

  const { data: { session } } = await supabase.auth.getSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const exportId = req.nextUrl.searchParams.get("export_id");
  if (!exportId) {
    return NextResponse.json({ error: "Missing export_id" }, { status: 400 });
  }

  const apiUrl = process.env.NEXT_PUBLIC_API_URL!;
  const resp = await fetch(`${apiUrl}/api/export/${exportId}`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  });

  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: "Export not found" }));
    return NextResponse.json(err, { status: resp.status });
  }

  const data = await resp.json();
  return NextResponse.json(data);
}

export async function POST(req: NextRequest) {
  const cookieStore = cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    { cookies: { get: (name: string) => cookieStore.get(name)?.value } }
  );

  const { data: { session } } = await supabase.auth.getSession();
  if (!session) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const body = await req.json();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL!;
  const resp = await fetch(`${apiUrl}/api/export`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${session.access_token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const data = await resp.json();
  return NextResponse.json(data, { status: resp.status });
}
