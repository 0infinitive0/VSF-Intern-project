/**
 * payment-client.ts — wraps the VNPay payment API (backend/src/api/
 * routes.py's POST /payments/vnpay, GET /payments/{id} — plan
 * 260818-vnpay-payment-and-email-confirmation). Mirrors booking-client.ts's
 * request<T>() error handling: a failed payment-creation call is something
 * the caller must surface, never something that silently degrades.
 *
 * There is no client-side call for the IPN endpoint (POST /payments/vnpay/ipn)
 * — VNPay calls that directly, server-to-server; this file never touches it.
 */
import type { CreateVnpayPaymentRequest, CreateVnpayPaymentResponse, Payment } from '../types'
import { authHeaders } from './auth-headers'

const BASE = (import.meta.env.VITE_API_BASE || '') + '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(await authHeaders()) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  const text = await res.text()
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      throw new Error(`Non-JSON response (${res.status}): ${text.slice(0, 200)}`)
    }
  }

  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? (data as { detail?: unknown }).detail
        : undefined
    throw new Error(typeof detail === 'string' ? detail : detail != null ? JSON.stringify(detail) : text)
  }

  return data as T
}

/** Creates a VNPay payment for one hold group and returns the signed URL to
 * redirect the browser to (`window.location.href = pay_url`) — this is a
 * real page navigation away from the SPA, not an in-app popup. */
export async function createVnpayPayment(payload: CreateVnpayPaymentRequest): Promise<CreateVnpayPaymentResponse> {
  return request('POST', '/payments/vnpay', payload)
}

/** Polls the authoritative payment status after the guest returns from
 * VNPay (App.tsx's consumeVnpayReturn) — never trust the return URL's own
 * query params for the verdict, only this. */
export async function getPaymentStatus(paymentId: string, temporaryUserRef: string): Promise<Payment> {
  const params = new URLSearchParams({ temporary_user_ref: temporaryUserRef })
  return request('GET', `/payments/${encodeURIComponent(paymentId)}?${params.toString()}`)
}
