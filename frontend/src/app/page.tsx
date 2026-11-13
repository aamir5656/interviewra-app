import { Features } from "@/components/landing/Features";
import { Footer } from "@/components/landing/Footer";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";

export default function HomePage() {
  return (
    <>
      <Hero />
      <Features />
      <HowItWorks />
      <Footer />
    </>
  );
}
