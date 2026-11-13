import { Suspense } from "react";

import { InterviewRoom } from "@/components/interview/InterviewRoom";

export const metadata = { title: "Interview | Interviewra" };

async function Room({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params; // runtime data: must be read inside <Suspense> (cacheComponents)
  return <InterviewRoom id={id} />;
}

export default function InterviewPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={null}>
      <Room params={params} />
    </Suspense>
  );
}
