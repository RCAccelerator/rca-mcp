import React, { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./RcaComponent.css";

interface RcaComponentProps {
  build: string;
  backendUrl?: string;
}

interface Tokens {
  input: number;
  output: number;
}

interface RcaAnalysis {
  summary: string;
  root_cause: string;
  failed_step: string;
  log_evidence: string;
  suggested_fix: string;
}

function Spinner() {
  return (
    <div className="flex justify-center items-center p-8">
      <div className="w-16 h-16 border-4 border-blue-500 border-dashed rounded-full animate-spin"></div>
    </div>
  );
}

export function RcaComponent(
  { build = "", backendUrl = "" }: RcaComponentProps,
) {
  const [status, setStatus] = useState<string[]>([]);
  const [report, setReport] = useState<RcaAnalysis | null>(null);
  const [error, setError] = useState("");
  const [logjuicerUrl, setLogjuicerUrl] = useState("");
  const [usage, setUsage] = useState<Tokens | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const eventSourceRef = useRef<EventSource | null>(null);

  async function getReport() {
    setStatus([]);
    setReport(null);
    setError("");
    setLogjuicerUrl("");
    setUsage(null);
    setIsLoading(true);

    if (!build) {
      setStatus(
        (_) => ["Build is missing, try adding ?build=... to the page url."]
      );
      setIsLoading(false);
      return;
    }
    let eventSource;
    if (eventSource) {
      eventSource.close();
    }

    function handleMessage(event, body) {
      setIsLoading(false);
      switch (event) {
        case "progress":
          setStatus((prevStatus) => [...prevStatus, body]);
          break;
        case "report":
          setReport(body);
          break;
        case "logjuicer_url":
          setLogjuicerUrl(body);
          break;
        case "usage":
          setUsage(body);
          break;
        case "status":
          console.log("Setting status", body);
          if (body != "completed") {
            setError(body);
          }
          if (eventSource) {
            eventSource.close();
          }
          eventSource = null;
          break;
      }
    }

    try {
      const submitRes = await fetch(
        `${backendUrl}/submit?build=${encodeURIComponent(build)}`,
        {
          method: "PUT",
        },
      );

      const submitData = await submitRes.json();

      if (submitData.status === "COMPLETED") {
        const reportRes = await fetch(
          `${backendUrl}/report?build=${encodeURIComponent(build)}`,
        );
        if (!reportRes.ok) {
          throw new Error("Failed to fetch completed report");
        }
        const reportData = await reportRes.json();
        reportData.forEach(([event, body]) => {
          handleMessage(event, body);
        });
        setIsLoading(false);
        return;
      }

      eventSource = new EventSource(
        `${backendUrl}/watch?build=${encodeURIComponent(build)}`,
      );

      eventSource.onmessage = (e) => {
        const [event, body] = JSON.parse(e.data);
        handleMessage(event, body);
      };

      eventSource.onerror = () => {
        setError(
          "Failed to connect to the server. Please ensure the backend is running and accessible.",
        );
        setIsLoading(false);
        if (eventSourceRef.current) {
          eventSourceRef.current.close();
          eventSourceRef.current = null;
        }
      };
    } catch (err) {
      console.error("RCA failed", err);
      setError(
        err instanceof Error ? err.message : "An unknown error occurred.",
      );
      setIsLoading(false);
    }
  }
  useEffect(() => {
    getReport();
    return () => { };
  }, [build]);
  return (
    <div className="bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-white min-h-screen flex flex-col items-center p-4 sm:p-6 lg:p-8 transition-colors duration-300">
      <div className="w-full max-w-4xl">
        <header className="text-center mb-8">
          <h1 className="text-4xl font-bold">RCAv2</h1>
          <p className="text-gray-600 dark:text-gray-400">
            Fast and accurate root cause analysis of Zuul CI Build failures.
          </p>
        </header>
        <main className="w-full flex flex-col items-center gap-6">
          {isLoading && <Spinner />}
          {error && (
            <div className="w-full bg-red-50 dark:bg-gray-800 border border-red-500 rounded-lg shadow-md p-6">
              <h2 className="text-xl font-semibold text-red-700 dark:text-red-400 border-b border-red-200 dark:border-gray-700 pb-2 mb-4">
                Error
              </h2>
              <pre className="text-red-600 dark:text-red-300 whitespace-pre-wrap break-words font-mono">{error}</pre>
            </div>
          )}
          {!isLoading && !error && (logjuicerUrl || status.length > 0) && (
            <div className="w-full bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg shadow-md p-6">
              <h2 className="text-xl font-semibold border-b border-gray-200 dark:border-gray-700 pb-2 mb-4">
                Analysis Status
              </h2>
              {logjuicerUrl && (
                <div className="mb-4">
                  <a
                    href={logjuicerUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block bg-blue-500 hover:bg-blue-600 text-white font-bold py-2 px-4 rounded-lg transition-colors duration-200"
                  >
                    View logjuicer report
                  </a>
                </div>
              )}
              <ul className="list-none p-0 m-0 font-mono text-sm space-y-2">
                {status.map((msg, index) => (
                  <li key={index} className="pt-1 break-words">{msg}</li>
                ))}
              </ul>
            </div>
          )}

          {report && (
            <div className="w-full bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-700 rounded-lg shadow-md p-6">
              <div className="flex flex-wrap justify-between items-center border-b border-gray-200 dark:border-gray-700 pb-2 mb-4 gap-2">
                <h2 className="text-xl font-semibold">
                  Analysis Result
                </h2>
                {usage && (
                  <div className="text-sm text-gray-500 dark:text-gray-400 font-mono">
                    Tokens: {usage.input} in / {usage.output} out
                  </div>
                )}
              </div>
              <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-700/50 rounded-md border border-gray-200 dark:border-gray-600">
                <span className="font-semibold">Build URL: </span>
                <a
                  href={build}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 dark:text-blue-400 hover:underline break-all"
                >
                  {build}
                </a>
              </div>
              <div className="prose dark:prose-invert max-w-none space-y-4">
                <div>
                  <h3 className="font-semibold text-lg">Summary</h3>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.summary}</ReactMarkdown>
                </div>
                <div>
                  <h3 className="font-semibold text-lg">Root Cause</h3>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.root_cause}</ReactMarkdown>
                </div>
                <div>
                  <h3 className="font-semibold text-lg">Failed Step</h3>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.failed_step}</ReactMarkdown>
                </div>
                <div>
                  <h3 className="font-semibold text-lg">Log Evidence</h3>
                  <pre className="whitespace-pre-wrap break-all bg-gray-100 dark:bg-gray-700 p-2 rounded"><code>{report.log_evidence}</code></pre>
                </div>
                <div>
                  <h3 className="font-semibold text-lg">Suggested Fix</h3>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{report.suggested_fix}</ReactMarkdown>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
