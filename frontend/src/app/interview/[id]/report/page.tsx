import { Suspense } from "react";

import { ReportView } from "@/components/report/ReportView";

export const metadata = { title: "Your report | Interviewra" };

async function Report({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; // runtime data: must be read inside <Suspense> (cacheComponents)
  return <ReportView id={id} />;
}

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={null}>
      <Report params={params} />
    </Suspense>
  );
}
