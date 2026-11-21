import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, Doc } from "../api";
import ChatPage from "./ChatPage";
import DocumentsPage from "./DocumentsPage";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    api: {
      documents: vi.fn(),
      upload: vi.fn(),
      deleteDocument: vi.fn(),
      conversations: vi.fn(),
      conversation: vi.fn(),
      deleteConversation: vi.fn(),
      ask: vi.fn(),
    },
  };
});

import { api } from "../api";
const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

const doc = (over: Partial<Doc> = {}): Doc => ({
  id: 1,
  name: "trip.pdf",
  size: 2048,
  status: "ready",
  error: "",
  pages: 6,
  chunk_count: 10,
  uploaded_at: "2026-11-01T00:00:00Z",
  ...over,
});

const pdf = (name = "trip.pdf") => new File(["%PDF-1.4"], name, { type: "application/pdf" });

beforeEach(() => {
  vi.resetAllMocks();
  mocked.documents.mockResolvedValue([doc()]);
  mocked.conversations.mockResolvedValue([]);
});

describe("DocumentsPage", () => {
  it("lists documents with their status", async () => {
    mocked.documents.mockResolvedValue([
      doc(),
      doc({ id: 2, name: "bad.pdf", status: "failed", error: "no extractable text (is it a scanned PDF?)" }),
    ]);
    render(<DocumentsPage />);
    expect(await screen.findByText("trip.pdf")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText(/scanned PDF/)).toBeInTheDocument();
  });

  it("warns instead of uploading when the same file was already uploaded", async () => {
    mocked.upload.mockRejectedValue(
      new ApiError(409, "You already uploaded this exact file as “trip.pdf”.", "duplicate_content")
    );
    render(<DocumentsPage />);
    await screen.findByText("trip.pdf");
    await userEvent.upload(screen.getByTestId("file-input"), pdf("trip-copy.pdf"));

    expect(await screen.findByText("Already uploaded")).toBeInTheDocument();
    expect(screen.getByText(/exact file as “trip.pdf”/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Replace" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText("Already uploaded")).not.toBeInTheDocument();
  });

  it("asks before replacing a different file with the same name, and replaces on request", async () => {
    mocked.upload
      .mockRejectedValueOnce(new ApiError(409, "A different file named “trip.pdf” already exists.", "name_exists"))
      .mockResolvedValueOnce(doc());
    render(<DocumentsPage />);
    await screen.findByText("trip.pdf");
    const file = pdf();
    await userEvent.upload(screen.getByTestId("file-input"), file);

    await screen.findByText("A file with this name exists");
    expect(mocked.upload).toHaveBeenCalledTimes(1);
    expect(mocked.upload).toHaveBeenLastCalledWith(file, false);

    await userEvent.click(screen.getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(mocked.upload).toHaveBeenCalledTimes(2));
    expect(mocked.upload).toHaveBeenLastCalledWith(file, true);
    await waitFor(() => expect(screen.queryByText("A file with this name exists")).not.toBeInTheDocument());
  });

  it("cancelling the replace prompt does not upload anything", async () => {
    mocked.upload.mockRejectedValue(new ApiError(409, "exists", "name_exists"));
    render(<DocumentsPage />);
    await screen.findByText("trip.pdf");
    await userEvent.upload(screen.getByTestId("file-input"), pdf());
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(mocked.upload).toHaveBeenCalledTimes(1);
  });

  it("shows other upload errors", async () => {
    mocked.upload.mockRejectedValue(new ApiError(413, "The file is larger than the 25 MB limit.", "too_large"));
    render(<DocumentsPage />);
    await screen.findByText("trip.pdf");
    await userEvent.upload(screen.getByTestId("file-input"), pdf("huge.pdf"));
    expect(await screen.findByText(/larger than the 25 MB limit/)).toBeInTheDocument();
  });

  it("deletes a document after confirmation", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    mocked.deleteDocument.mockResolvedValue(undefined);
    render(<DocumentsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(mocked.deleteDocument).toHaveBeenCalledWith(1);
  });
});

describe("ChatPage", () => {
  const renderChat = () =>
    render(
      <MemoryRouter>
        <ChatPage />
      </MemoryRouter>
    );

  it("sends a question and shows the answer with clickable sources", async () => {
    mocked.ask.mockResolvedValue({
      conversation: { id: 7, title: "Busan?", updated_at: "" },
      messages: [
        { id: 1, role: "user", content: "How many nights in Busan?", sources: [], created_at: "" },
        {
          id: 2,
          role: "assistant",
          content: "3 nights.",
          created_at: "",
          sources: [{ document_id: 1, document: "korea.pdf", page: 4, snippet: "Busan (3 nights) then Jeju" }],
        },
      ],
    });
    renderChat();
    await userEvent.type(screen.getByLabelText("Question"), "How many nights in Busan?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText("3 nights.")).toBeInTheDocument();
    expect(mocked.ask).toHaveBeenCalledWith("How many nights in Busan?", undefined);

    await userEvent.click(screen.getByRole("button", { name: "korea.pdf · p.4" }));
    expect(screen.getByText(/Busan \(3 nights\) then Jeju/)).toBeInTheDocument();
  });

  it("keeps the question and shows the reason when the model is unreachable", async () => {
    mocked.ask.mockRejectedValue(new ApiError(503, "The language model isn't reachable right now. Is Ollama running?"));
    renderChat();
    const box = screen.getByLabelText("Question");
    await userEvent.type(box, "Where do we land?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Ollama/);
    expect(box).toHaveValue("Where do we land?");
    expect(screen.queryByText("Searching your documents…")).not.toBeInTheDocument();
  });

  it("points to the Documents page when nothing is ready yet", async () => {
    mocked.documents.mockResolvedValue([doc({ status: "processing" })]);
    renderChat();
    expect(await screen.findByText(/no processed documents yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload a PDF" })).toHaveAttribute("href", "/documents");
  });
});
