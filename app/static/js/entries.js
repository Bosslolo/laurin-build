// Beverage Consumption Management
class BeverageConsumption {
    constructor() {
        this.userId = this.getUserId();
        this.order = new Map(); // beverage_id -> quantity
        this.beverageData = new Map(); // beverage_id -> {name, price}
        this.consumedData = new Map(); // beverage_id -> consumed_count
        
        this.init();
    }
    
    init() {
        this.loadBeverageData();
        this.loadConsumedData();
        this.setupEventListeners();
    }
    
    getUserId() {
        // Get user ID from backend data or URL parameters
        if (window.userData && Object.prototype.hasOwnProperty.call(window.userData, 'id')) {
            return String(window.userData.id);
        }
        
        // Fallback to URL parameters
        const urlParams = new URLSearchParams(window.location.search);
        const userIdParam = urlParams.get('user_id');
        if (userIdParam !== null) return userIdParam;
        
        // As a final fallback, if on guests page, treat as guest user (id 0)
        if (window.location && window.location.pathname && window.location.pathname.includes('/guests')) {
            return '0';
        }
        
        return null;
    }
    
    loadBeverageData() {
        // Load beverage data from the DOM
        const beverageItems = document.querySelectorAll('.beverage-card');
        beverageItems.forEach(item => {
            const beverageId = item.dataset.beverageId;
            const name = item.querySelector('.beverage-name').textContent;
            const priceText = item.querySelector('.beverage-price').textContent;
            const price = parseFloat(priceText.replace(' €', ''));
            
            this.beverageData.set(beverageId, { name, price });
        });
    }
    
    loadConsumedData() {
        // Load consumed data from the DOM (if available)
        const consumedCounts = document.querySelectorAll('.consumed-count');
        consumedCounts.forEach(count => {
            const beverageItem = count.closest('.beverage-card');
            const beverageId = beverageItem.dataset.beverageId;
            const consumed = parseInt(count.textContent) || 0;
            
            this.consumedData.set(beverageId, consumed);
        });
        
        // Also load from backend data if available
        if (window.consumptionsData) {
            window.consumptionsData.forEach(consumption => {
                this.consumedData.set(consumption.beverage_id.toString(), consumption.total_quantity || consumption.count);
            });
        }
        
        // Update consumed count displays
        this.updateConsumedDisplays();
    }
    
    updateConsumedDisplays() {
        this.consumedData.forEach((count, beverageId) => {
            const beverageItem = document.querySelector(`[data-beverage-id="${beverageId}"]`);
            if (beverageItem) {
                const consumedCountElement = beverageItem.querySelector('.consumed-count');
                if (consumedCountElement) {
                    consumedCountElement.textContent = count;
                }
            }
        });
    }
    
    setupEventListeners() {
        // Quantity control buttons with debouncing
        document.querySelectorAll('.quantity-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                // Prevent multiple rapid clicks
                if (e.currentTarget.disabled) return;
                
                const action = e.currentTarget.dataset.action;
                const beverageItem = e.currentTarget.closest('.beverage-card');
                const beverageId = beverageItem.dataset.beverageId;
                
                if (beverageId) {
                    // Store button reference before setTimeout
                    const button = e.currentTarget;
                    // Temporarily disable button to prevent rapid clicks
                    const originalDisabled = button.disabled;
                    button.disabled = true;
                    
                    // Update quantity
                    this.updateQuantity(beverageId, action);
                    
                    // Re-enable button after debounce, but respect original disabled state
                    setTimeout(() => {
                        // Only re-enable if it wasn't originally disabled (e.g., for no price items)
                        if (!originalDisabled) {
                            button.disabled = false;
                        }
                    }, 300); // 300ms debounce
                }
            });
        });
        
        // Done button
        document.getElementById('doneBtn').addEventListener('click', () => {
            this.handleDoneClick();
        });
        
        // Confirm order button in modal
        document.getElementById('confirmOrderBtn').addEventListener('click', () => {
            this.confirmOrder();
        });
        
        // Help button for roles 4 and 5
        const helpBtn = document.getElementById('helpBtn');
        if (helpBtn) {
            helpBtn.addEventListener('click', () => {
                alert('Bei Problemen meldet euch bei Laurin Domenig in Lela 6.');
            });
        }
    }
    
    updateQuantity(beverageId, action) {
        const currentQuantity = this.order.get(beverageId) || 0;
        let newQuantity = currentQuantity;
        
        if (action === 'increase') {
            newQuantity = currentQuantity + 1;
        } else if (action === 'decrease' && currentQuantity > 0) {
            newQuantity = currentQuantity - 1;
        }
        
        this.order.set(beverageId, newQuantity);
        this.updateQuantityDisplay(beverageId, newQuantity);
    }
    
    updateQuantityDisplay(beverageId, quantity) {
        const beverageItem = document.querySelector(`[data-beverage-id="${beverageId}"]`);
        const quantityDisplay = beverageItem.querySelector('.quantity-display');
        quantityDisplay.textContent = quantity;
        
        // Update button states - only disable decrease button when quantity is 0
        const decreaseBtn = beverageItem.querySelector('[data-action="decrease"]');
        const increaseBtn = beverageItem.querySelector('[data-action="increase"]');
        
        // Only disable decrease button when quantity is 0, never disable increase button
        if (decreaseBtn) {
            decreaseBtn.disabled = quantity === 0;
        }
        
        // Ensure increase button is always enabled (unless it's disabled for other reasons like no price)
        if (increaseBtn && !increaseBtn.hasAttribute('data-originally-disabled')) {
            increaseBtn.disabled = false;
        }
    }
    
    
    handleDoneClick() {
        const hasItems = Array.from(this.order.values()).some(qty => qty > 0);
        
        if (!hasItems) {
            // No items selected, redirect to index
            window.location.href = '/';
        } else {
            // Show confirmation modal
            this.showConfirmationModal();
        }
    }
    
    showConfirmationModal() {
        const modal = new bootstrap.Modal(document.getElementById('confirmationModal'));
        const modalOrderItems = document.getElementById('modalOrderItems');
        
        // Clear existing modal items
        modalOrderItems.innerHTML = '';
        
        // Add items to modal
        this.order.forEach((quantity, beverageId) => {
            if (quantity > 0) {
                const beverage = this.beverageData.get(beverageId);
                
                const modalItem = document.createElement('div');
                modalItem.className = 'modal-order-item';
                modalItem.innerHTML = `
                    <div class="modal-order-item-name">${beverage.name}</div>
                    <div class="modal-order-item-quantity">${quantity}</div>
                `;
                
                modalOrderItems.appendChild(modalItem);
            }
        });
        
        // Show modal
        modal.show();
    }
    
    async confirmOrder() {
        const confirmBtn = document.getElementById('confirmOrderBtn');
        const originalText = confirmBtn.innerHTML;
        
        // Show loading state
        confirmBtn.disabled = true;
        confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Processing...';
        
        try {
            // Process each beverage in the order
            const promises = [];
            
            this.order.forEach((quantity, beverageId) => {
                if (quantity > 0) {
                    // Send quantity in single API call instead of multiple calls
                    promises.push(this.addConsumption(beverageId, quantity));
                }
            });
            
            // Wait for all consumptions to be added
            await Promise.all(promises);
            
            // Show success message
            this.showSuccessMessage('Order confirmed successfully!');
            
            // Close modal and redirect
            const modal = bootstrap.Modal.getInstance(document.getElementById('confirmationModal'));
            modal.hide();
            
            setTimeout(() => {
                window.location.href = '/';
            }, 1500);
            
        } catch (error) {
            console.error('Error confirming order:', error);
            this.showErrorMessage('Failed to confirm order. Please try again.');
            
            // Reset button
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = originalText;
        }
    }
    
    async addConsumption(beverageId, quantity = 1) {
        const response = await fetch('/add_consumption', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                user_id: this.userId,
                beverage_id: beverageId,
                quantity: quantity
            })
        });
        
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Failed to add consumption');
        }
        
        return response.json();
    }
    
    showSuccessMessage(message) {
        this.showMessage(message, 'success');
    }
    
    showErrorMessage(message) {
        this.showMessage(message, 'danger');
    }
    
    showMessage(message, type) {
        // Remove existing messages
        const existingMessages = document.querySelectorAll('.alert');
        existingMessages.forEach(msg => msg.remove());
        
        // Create new message
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
        alertDiv.style.position = 'fixed';
        alertDiv.style.top = '20px';
        alertDiv.style.right = '20px';
        alertDiv.style.zIndex = '9999';
        alertDiv.style.minWidth = '300px';
        
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(alertDiv);
        
        // Auto-hide success messages
        if (type === 'success') {
            setTimeout(() => {
                alertDiv.remove();
            }, 3000);
        }
    }
}

// PIN Management functionality
class PinManagement {
    constructor() {
        this.pinOverlay = document.getElementById('pinOverlay');
        this.pinInput = document.getElementById('pinInput');
        this.pinSubmit = document.getElementById('pinSubmit');
        this.pinCancel = document.getElementById('pinCancel');
        this.pinError = document.getElementById('pinError');
        this.createPinBtn = document.getElementById('createPinBtn');
        this.changePinBtn = document.getElementById('changePinBtn');
        
        if (this.pinOverlay) {
            this.init();
        }
    }
    
    init() {
        
        // Add event listeners
        if (this.createPinBtn) {
            this.createPinBtn.addEventListener('click', () => this.showCreatePinOverlay());
        }
        
        if (this.changePinBtn) {
            this.changePinBtn.addEventListener('click', () => this.showChangePinMessage());
        }
        
        if (this.pinSubmit) {
            this.pinSubmit.addEventListener('click', () => this.submitPin());
        }
        
        if (this.pinCancel) {
            this.pinCancel.addEventListener('click', () => this.cancelPin());
        }
        
        if (this.pinInput) {
            this.pinInput.addEventListener('keydown', (e) => this.handleKeydown(e));
            this.pinInput.addEventListener('input', (e) => this.handleInput(e));
        }
    }
    
    handleKeydown(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            this.submitPin();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            this.cancelPin();
        }
    }
    
    handleInput(e) {
        // Only allow digits
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
    }
    
    showCreatePinOverlay() {
        // Clear any previous errors
        this.pinError.style.display = 'none';
        this.pinInput.value = '';
        
        // Show overlay
        this.pinOverlay.style.display = 'flex';
        this.pinInput.focus();
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
    }
    
    showChangePinMessage() {
        alert('Please consult with Laurin Domenig in Lela 6 for help.');
    }
    
    async submitPin() {
        const pin = this.pinInput.value.trim();
        
        if (!pin) {
            this.showError('Please enter a PIN');
            return;
        }
        
        if (pin.length !== 4 || !/^\d{4}$/.test(pin)) {
            this.showError('PIN must be exactly 4 digits');
            return;
        }
        
        // Disable submit button during request
        this.pinSubmit.disabled = true;
        this.pinSubmit.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        
        try {
            const response = await fetch('/create_user_pin', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    user_id: window.userId,
                    pin: pin 
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // PIN created successfully
                this.hideOverlay();
                // Show success message and reload page to update UI
                alert('PIN created successfully!');
                window.location.reload();
            } else {
                // PIN creation failed
                this.showError(data.error || 'Error creating PIN');
                this.pinInput.value = '';
                this.pinInput.focus();
            }
        } catch (error) {
            console.error('PIN creation error:', error);
            this.showError('Network error. Please try again.');
        } finally {
            // Re-enable submit button
            this.pinSubmit.disabled = false;
            this.pinSubmit.innerHTML = '<i class="fas fa-check"></i>';
        }
    }
    
    cancelPin() {
        this.hideOverlay();
    }
    
    showError(message) {
        this.pinError.querySelector('span').textContent = message;
        this.pinError.style.display = 'flex';
        
        // Hide error after 3 seconds
        setTimeout(() => {
            this.pinError.style.display = 'none';
        }, 3000);
    }
    
    hideOverlay() {
        this.pinOverlay.style.animation = 'fadeOut 0.3s ease forwards';
        document.body.style.overflow = '';
        
        setTimeout(() => {
            this.pinOverlay.style.display = 'none';
        }, 300);
    }
}

// Payment Management
class PaymentManagement {
    constructor() {
        this.userId = this.getUserId();
        this.paymentSection = document.getElementById('paymentSection');
        this.paymentBtn = document.getElementById('paymentBtn');
        this.closePaymentBtn = document.getElementById('closePaymentBtn');
        this.generatePayPalBtn = document.getElementById('generatePayPalBtn');
        this.generateReceiptBtn = document.getElementById('generateReceiptBtn');
        this.payByCardBtn = document.getElementById('payByCardBtn');
        this.cashRequestBtn = document.getElementById('cashRequestBtn');
        this.totalAmountElement = document.getElementById('totalAmount');
        this.paymentDetailsElement = document.getElementById('paymentDetails');
        this.currentPaymentId = null;
        
        this.setupEventListeners();
    }
    
    getUserId() {
        if (window.userData && Object.prototype.hasOwnProperty.call(window.userData, 'id')) {
            return window.userData.id;
        }
        
        const urlParams = new URLSearchParams(window.location.search);
        const userIdParam = urlParams.get('user_id');
        if (userIdParam !== null) return parseInt(userIdParam);
        
        if (window.location && window.location.pathname && window.location.pathname.includes('/guests')) {
            return 0;
        }
        
        return null;
    }
    
    setupEventListeners() {
        if (this.paymentBtn) {
            this.paymentBtn.addEventListener('click', () => this.showPaymentSection());
        }
        
        if (this.closePaymentBtn) {
            this.closePaymentBtn.addEventListener('click', () => this.hidePaymentSection());
        }
        
        if (this.generatePayPalBtn) {
            this.generatePayPalBtn.addEventListener('click', () => this.generatePayPalQR());
        }
        if (this.payByCardBtn) {
            this.payByCardBtn.addEventListener('click', () => this.payByCard());
        }
        if (this.cashRequestBtn) {
            this.cashRequestBtn.addEventListener('click', () => this.requestCashCollection());
        }
        
        // Card reader removed
        
        if (this.generateReceiptBtn) {
            this.generateReceiptBtn.addEventListener('click', () => this.generateReceipt());
        }
        
        // Payment method selection removed
        
        // Add event listener for receipt button in modal
        const getReceiptBtn = document.getElementById('getReceiptBtn');
        if (getReceiptBtn) {
            getReceiptBtn.addEventListener('click', () => {
                this.generateReceipt();
                // Close the modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('paypalModal'));
                if (modal) modal.hide();
            });
        }
        
    }

    async payByCard() {
        try {
            const amountText = this.totalAmountElement.textContent.replace('€', '');
            const amountEuros = parseFloat(amountText);
            if (!amountEuros || amountEuros <= 0) {
                alert('No payment amount to process.');
                return;
            }

            this.payByCardBtn.disabled = true;
            const original = this.payByCardBtn.innerHTML;
            this.payByCardBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Redirecting...';

            const resp = await fetch('/api/payment/stripe/checkout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: this.userId, amount_euros: amountEuros })
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Error: ' + (data.error || 'Failed to start checkout'));
                return;
            }
            // Redirect to Stripe hosted page
            window.location.href = data.checkout_url;
        } catch (e) {
            alert('Network error starting card payment');
        } finally {
            if (this.payByCardBtn) {
                this.payByCardBtn.disabled = false;
                this.payByCardBtn.innerHTML = '<i class="fas fa-credit-card"></i> Pay by Card / Apple Pay';
            }
        }
    }

    async requestCashCollection() {
        try {
            const amountText = (this.totalAmountElement?.textContent || '€0')
                .replace('€', '')
                .replace(',', '.')
                .trim();
            const amountEuros = parseFloat(amountText);

            if (!amountEuros || amountEuros <= 0) {
                alert('Derzeit gibt es keinen offenen Betrag für eine Barzahlung.');
                return;
            }

            const confirmed = confirm('Barzahlung anfordern?\nEine Person vom Team wird den Betrag in den nächsten Tagen kassieren.');
            if (!confirmed) return;

            if (this.cashRequestBtn) {
                this.cashRequestBtn.disabled = true;
                this.cashRequestBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> wird gesendet...';
            }

            const response = await fetch('/api/payment/cash-request', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    user_id: this.userId,
                    amount_cents: Math.round(amountEuros * 100),
                }),
            });

            const data = await response.json();

            if (data.success) {
                this.showPaymentNotification('📬 Barzahlung wurde gemeldet – jemand meldet sich in den nächsten Tagen bei dir.');
            } else {
                alert('Fehler beim Melden der Barzahlung: ' + (data.error || 'Unbekannter Fehler'));
            }
        } catch (error) {
            console.error('Cash request error:', error);
            alert('Fehler beim Senden der Barzahlungs-Anfrage. Bitte später erneut versuchen.');
        } finally {
            if (this.cashRequestBtn) {
                this.cashRequestBtn.disabled = false;
                this.cashRequestBtn.innerHTML = '<i class="fas fa-hand-holding-euro"></i> Bar bezahlen';
            }
        }
    }
    
    async showPaymentSection() {
        try {
            // Show loading state
            this.paymentBtn.disabled = true;
            this.paymentBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Loading...';
            
            // Calculate payment amount
            const response = await fetch('/api/payment/calculate', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ user_id: this.userId })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.displayPaymentInfo(data);
                this.paymentSection.style.display = 'block';
                this.paymentBtn.style.display = 'none';
                
                // Check if user has any paid payments to show receipt button
                this.checkForPaidPayments();
            } else {
                alert('Error calculating payment: ' + data.error);
            }
        } catch (error) {
            console.error('Payment calculation error:', error);
            alert('Error calculating payment. Please try again.');
        } finally {
            // Reset button state
            this.paymentBtn.disabled = false;
            this.paymentBtn.innerHTML = '<i class="fas fa-credit-card"></i> View Payment';
        }
    }
    
    displayPaymentInfo(data) {
        // Update total amount
        this.totalAmountElement.textContent = `€${data.total_amount_euros.toFixed(2)}`;
        
        // Display consumption details
        let detailsHTML = '<div class="consumption-details">';
        detailsHTML += '<h6>Consumption Details:</h6>';
        
        // Show date range if available
        if (data.date_range) {
            detailsHTML += `<div class="date-range">
                <small class="text-muted">
                    <i class="fas fa-calendar"></i> 
                    ${data.is_all_time ? 'All time' : 'Current month'}: ${data.date_range}
                </small>
            </div>`;
        }
        
        detailsHTML += '<div class="consumption-list">';
        
        data.consumption_details.forEach(detail => {
            detailsHTML += `
                <div class="consumption-item">
                    <span class="beverage-name">${detail.beverage_name}</span>
                    <span class="quantity">${detail.quantity}x</span>
                    <span class="unit-price">€${(detail.unit_price_cents / 100).toFixed(2)}</span>
                    <span class="total-price">€${(detail.total_cents / 100).toFixed(2)}</span>
                </div>
            `;
        });
        
        detailsHTML += '</div>';
        detailsHTML += `<div class="total-summary">
            <strong>Total: €${data.total_amount_euros.toFixed(2)}</strong>
            ${data.is_all_time ? '<br><small class="text-muted">Includes all unpaid consumptions</small>' : ''}
        </div>`;
        detailsHTML += '</div>';
        
        this.paymentDetailsElement.innerHTML = detailsHTML;
    }
    
    hidePaymentSection() {
        this.paymentSection.style.display = 'none';
        this.paymentBtn.style.display = 'block';
    }
    
    async generatePayPalQR() {
        try {
            // Get current payment amount
            const amountText = this.totalAmountElement.textContent.replace('€', '');
            const amountEuros = parseFloat(amountText);
            
            if (amountEuros <= 0) {
                alert('No payment amount to process.');
                return;
            }
            
            // Show loading state
            this.generatePayPalBtn.disabled = true;
            this.generatePayPalBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generating...';
            
            // Generate PayPal QR
            const response = await fetch('/api/payment/paypal-qr', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    user_id: this.userId,
                    amount_euros: amountEuros
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                // Store the payment ID for receipt generation
                this.currentPaymentId = data.payment_id;
                this.showPayPalModal(data.qr_data);
                
                // PayPal QR code generated successfully
            } else {
                alert('Error generating PayPal QR: ' + data.error);
            }
        } catch (error) {
            console.error('PayPal QR generation error:', error);
            alert('Error generating PayPal QR. Please try again.');
        } finally {
            // Reset button state
            this.generatePayPalBtn.disabled = false;
            this.generatePayPalBtn.innerHTML = '<i class="fab fa-paypal"></i> Generate PayPal QR Code';
        }
    }
    
    showPayPalModal(qrData) {
        // Update modal content
        document.getElementById('paypalDescription').textContent = qrData.description;
        document.getElementById('paypalAmount').textContent = `€${qrData.amount_euros.toFixed(2)}`;
        
        // Use the direct PayPal URL for QR code
        this.generateQRCode(qrData.paypal_url, 'paypalQRCode');
        
        // Add fallback link
        const linkEl = document.getElementById('paypalWebLink');
        if (linkEl) {
            linkEl.href = qrData.paypal_url;
        }
        
        // Show receipt button if payment ID is available
        const getReceiptBtn = document.getElementById('getReceiptBtn');
        if (getReceiptBtn && this.currentPaymentId) {
            getReceiptBtn.style.display = 'inline-block';
        }
        
        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('paypalModal'));
        modal.show();
    }
    
    generateQRCode(text, elementId) {
        // Simple QR code generation using qrcode.js library
        // You'll need to include the qrcode.js library in your HTML
        const qrContainer = document.getElementById(elementId);
        qrContainer.innerHTML = ''; // Clear placeholder
        
        // Create QR code using a simple approach
        // For production, you should use a proper QR code library
        const qrImg = document.createElement('img');
        qrImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encodeURIComponent(text)}`;
        qrImg.alt = 'PayPal QR Code';
        qrImg.className = 'img-fluid';
        qrContainer.appendChild(qrImg);
    }
    
    async checkForPaidPayments() {
        try {
            const response = await fetch(`/api/payment/user-payments/${this.userId}`);
            const data = await response.json();
            
            if (data.success && data.payments.length > 0) {
                // Find the most recent paid payment
                const paidPayment = data.payments.find(p => p.payment_status === 'paid');
                if (paidPayment) {
                    this.currentPaymentId = paidPayment.id;
                    this.generateReceiptBtn.style.display = 'inline-block';
                }
            }
        } catch (error) {
            console.error('Error checking paid payments:', error);
        }
    }
    
    generateReceipt() {
        if (this.currentPaymentId) {
            // Open receipt in new window
            const receiptUrl = `/payment_receipt.html?payment_id=${this.currentPaymentId}`;
            window.open(receiptUrl, '_blank', 'width=500,height=700,scrollbars=yes,resizable=yes');
        } else {
            alert('No paid payment found to generate receipt for.');
        }
    }
    
    handlePaymentMethodChange() {
        // Only PayPal remains
        if (this.generatePayPalBtn) this.generatePayPalBtn.style.display = 'inline-block';
    }
    
    getAmountInCents() {
        const amountText = this.totalAmountElement.textContent;
        const amount = parseFloat(amountText.replace('€', '').replace(',', '.'));
        return Math.round(amount * 100);
    }
    
    showPaymentNotification(message) {
        // Create a temporary notification
        const notification = document.createElement('div');
        notification.className = 'alert alert-info alert-dismissible fade show position-fixed';
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        notification.innerHTML = `
            <i class="fas fa-info-circle"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(notification);
        
        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (notification.parentNode) {
                notification.parentNode.removeChild(notification);
            }
        }, 5000);
    }
}

// Initialize beverage consumption when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    new BeverageConsumption();
    new PinManagement();
    new PaymentManagement();
});