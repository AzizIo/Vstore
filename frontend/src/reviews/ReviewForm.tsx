import { useEffect, useRef, useState, type FormEvent } from "react";

import { createReview, fetchReviewEligibility } from "./api";
import "./reviews.css";

const MAX_COMMENT_LENGTH = 2000;

export function ReviewForm({ orderId, accessToken, onSubmitted }: { orderId: string; accessToken: string; onSubmitted?: () => void }) {
  const [eligible, setEligible] = useState(false);
  const [alreadyReviewed, setAlreadyReviewed] = useState(false);
  const [checking, setChecking] = useState(true);
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);

  useEffect(() => {
    const controller = new AbortController();
    setChecking(true);
    setError("");
    fetchReviewEligibility(orderId, accessToken, controller.signal)
      .then((result) => { setEligible(result.eligible); setAlreadyReviewed(result.already_reviewed); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Unable to check review availability."); })
      .finally(() => { if (!controller.signal.aborted) setChecking(false); });
    return () => controller.abort();
  }, [orderId, accessToken]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || !eligible || rating < 1 || rating > 5) return;
    submitting.current = true;
    setPending(true);
    setError("");
    setMessage("");
    try {
      await createReview(orderId, rating, comment.trim(), accessToken);
      setSubmitted(true);
      setEligible(false);
      setAlreadyReviewed(true);
      setMessage("Your review was submitted. Reviews cannot be edited.");
      setComment("");
      onSubmitted?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to submit your review. Please retry.");
    } finally {
      submitting.current = false;
      setPending(false);
    }
  }

  if (checking) return <p className="review-form-state" role="status">Checking review availability...</p>;
  if (submitted) return <p className="review-form-state" role="status">{message}</p>;
  if (!eligible) return alreadyReviewed ? <p className="review-form-state" role="status">This order has already been reviewed.</p> : error ? <div className="review-form-state" role="alert"><p>{error}</p><button type="button" className="text-button" onClick={() => window.location.reload()}>Try again</button></div> : null;

  return (
    <form className="review-form" onSubmit={(event) => void submit(event)} aria-labelledby="review-form-title">
      <h3 id="review-form-title">Leave a review</h3>
      <p>Only completed, verified NFT transfers can be reviewed. Reviews cannot be edited.</p>
      <fieldset disabled={pending}>
        <legend>Your rating</legend>
        <div className="review-rating-options">
          {[1, 2, 3, 4, 5].map((value) => <label key={value}>
            <input aria-label={`${value} ${value === 1 ? "star" : "stars"}`} type="radio" name={`review-rating-${orderId}`} value={value} checked={rating === value} onChange={() => setRating(value)} required />
            <span aria-hidden="true">{value} ★</span><span className="sr-only">{value} {value === 1 ? "star" : "stars"}</span>
          </label>)}
        </div>
      </fieldset>
      <label className="review-comment-label">Comment (optional)
        <textarea value={comment} maxLength={MAX_COMMENT_LENGTH} disabled={pending} onChange={(event) => setComment(event.target.value)} rows={3} />
      </label>
      <div className="review-submit-row"><span>{comment.length}/{MAX_COMMENT_LENGTH}</span><button className="primary-button" type="submit" disabled={pending || rating < 1}>{pending ? "Submitting…" : "Submit review"}</button></div>
      {error && <p role="alert" className="review-form-error">{error}</p>}
      {message && <p role="status" className="review-form-success">{message}</p>}
    </form>
  );
}
