// Fuzzy Search functionality for user cards
class UserSearch {
    constructor() {
        this.searchInput = document.getElementById('userSearch');
        this.clearButton = document.getElementById('clearSearch');
        this.resultsCount = document.getElementById('searchResultsCount');
        this.userCards = document.querySelectorAll('.user-card-container');
        this.userGrid = document.getElementById('userGrid');
        
        this.init();
    }
    
    init() {
        if (!this.searchInput) return;
        
        // Add event listeners
        this.searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
        this.searchInput.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.clearButton.addEventListener('click', () => this.clearSearch());
        
        // Initial count
        this.updateResultsCount(this.userCards.length);
    }
    
    handleSearch(query) {
        const searchTerm = query.toLowerCase().trim();
        
        if (searchTerm === '') {
            this.showAllCards();
            this.clearButton.style.display = 'none';
            this.toggleNoResultsMessage(false);
        } else {
            this.filterCards(searchTerm);
            this.clearButton.style.display = 'block';
        }
        
        this.updateResultsCount(this.getVisibleCards().length);
    }
    
    filterCards(searchTerm) {
        let visibleCount = 0;
        
        this.userCards.forEach((card, index) => {
            const userName = card.dataset.userName.toLowerCase();
            const firstName = card.dataset.userFirst.toLowerCase();
            const lastName = card.dataset.userLast.toLowerCase();
            
            // Fuzzy search logic
            const isMatch = this.fuzzyMatch(userName, searchTerm) ||
                           this.fuzzyMatch(firstName, searchTerm) ||
                           this.fuzzyMatch(lastName, searchTerm);
            
            if (isMatch) {
                card.classList.remove('hidden');
                card.style.animationDelay = `${visibleCount * 0.1}s`;
                visibleCount++;
            } else {
                card.classList.add('hidden');
            }
        });
        
        this.toggleNoResultsMessage(visibleCount === 0);
    }
    
    fuzzyMatch(text, pattern) {
        let patternIdx = 0;
        let textIdx = 0;
        
        while (textIdx < text.length && patternIdx < pattern.length) {
            if (text[textIdx] === pattern[patternIdx]) {
                patternIdx++;
            }
            textIdx++;
        }
        
        return patternIdx === pattern.length;
    }
    
    showAllCards() {
        this.userCards.forEach((card, index) => {
            card.classList.remove('hidden');
            card.style.animationDelay = `${index * 0.1}s`;
        });
    }
    
    getVisibleCards() {
        return Array.from(this.userCards).filter(card => !card.classList.contains('hidden'));
    }
    
    toggleNoResultsMessage(show) {
        let noResultsMsg = document.getElementById('noResultsMessage');
        
        if (show && !noResultsMsg) {
            noResultsMsg = document.createElement('div');
            noResultsMsg.id = 'noResultsMessage';
            noResultsMsg.className = 'col-12 no-results';
            noResultsMsg.innerHTML = `
                <i class="fas fa-search"></i>
                <h4>No users found</h4>
                <p>Try adjusting your search terms</p>
            `;
            this.userGrid.appendChild(noResultsMsg);
        } else if (!show && noResultsMsg) {
            noResultsMsg.remove();
        }
    }
    
    clearSearch() {
        this.searchInput.value = '';
        this.showAllCards();
        this.clearButton.style.display = 'none';
        this.toggleNoResultsMessage(false);
        this.updateResultsCount(this.userCards.length);
        this.searchInput.focus();
    }
    
    updateResultsCount(count) {
        if (this.resultsCount) {
            this.resultsCount.textContent = `${count} user${count !== 1 ? 's' : ''} found`;
        }
    }
    
    handleKeydown(e) {
        if (e.key === 'Escape') {
            this.clearSearch();
        }
    }
}

// Simple PIN Authentication
class PinAuth {
    constructor() {
        this.pinOverlay = document.getElementById('pinOverlay');
        this.pinInput = document.getElementById('pinInput');
        this.pinSubmit = document.getElementById('pinSubmit');
        this.pinCancel = document.getElementById('pinCancel');
        this.pinError = document.getElementById('pinError');
        this.pinUserInfo = document.getElementById('pinUserInfo');
        this.currentUser = null;
        
        this.init();
    }
    
    init() {
        if (!this.pinOverlay) return;
        
        this.pinSubmit.addEventListener('click', () => this.submitPin());
        this.pinCancel.addEventListener('click', () => this.hideOverlay());
        this.pinInput.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.pinInput.addEventListener('input', (e) => this.handleInput(e));
    }
    
    handleKeydown(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            this.submitPin();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            this.hideOverlay();
        }
    }
    
    handleInput(e) {
        // Only allow digits
        e.target.value = e.target.value.replace(/[^0-9]/g, '');
    }
    
    showPinForUser(userId, userName) {
        this.currentUser = { id: userId, name: userName };
        this.pinUserInfo.textContent = `Please enter PIN for ${userName}`;
        this.pinInput.value = '';
        this.pinError.style.display = 'none';
        this.pinOverlay.style.display = 'flex';
        this.pinInput.focus();
        document.body.style.overflow = 'hidden';
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
        
        if (!this.currentUser) {
            this.showError('No user selected');
            return;
        }
        
        this.pinSubmit.disabled = true;
        this.pinSubmit.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        
        try {
            const response = await fetch('/verify_pin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    user_id: this.currentUser.id,
                    pin: pin 
                })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                // PIN verified successfully - redirect to entries
                window.location.href = `/entries?user_id=${this.currentUser.id}`;
            } else {
                this.showError(data.error || 'Invalid PIN');
                this.pinInput.value = '';
                this.pinInput.focus();
            }
        } catch (error) {
            this.showError('Network error. Please try again.');
        } finally {
            this.pinSubmit.disabled = false;
            this.pinSubmit.innerHTML = '<i class="fas fa-check"></i>';
        }
    }
    
    hideOverlay() {
        this.pinOverlay.style.display = 'none';
        document.body.style.overflow = '';
        this.currentUser = null;
    }
    
    showError(message) {
        this.pinError.querySelector('span').textContent = message;
        this.pinError.style.display = 'flex';
        
        setTimeout(() => {
            this.pinError.style.display = 'none';
        }, 3000);
    }
}

// Simple User Click Handler
class UserClickHandler {
    constructor() {
        this.pinAuth = new PinAuth();
        this.init();
    }
    
    init() {
        const userCards = document.querySelectorAll('.user-card');
        userCards.forEach(card => {
            card.addEventListener('click', (e) => this.handleUserClick(e));
        });
    }
    
    async handleUserClick(e) {
        e.preventDefault();
        
        const userCard = e.currentTarget;
        const userContainer = userCard.closest('.user-card-container');
        const userId = this.extractUserIdFromHref(userCard.href);
        const userName = userContainer.dataset.userName;
        
        // Check if user has PIN by making a simple request
        try {
            const response = await fetch('/check_user_pin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            });
            
            const data = await response.json();
            
            if (response.ok && data.success) {
                if (data.has_pin) {
                    // User has PIN, show PIN overlay
                    this.pinAuth.showPinForUser(userId, userName);
                } else {
                    // User has no PIN, proceed directly
                    window.location.href = userCard.href;
                }
            } else {
                // Fallback: proceed directly
                window.location.href = userCard.href;
            }
        } catch (error) {
            // Fallback: proceed directly
            window.location.href = userCard.href;
        }
    }
    
    extractUserIdFromHref(href) {
        const url = new URL(href);
        return parseInt(url.searchParams.get('user_id'));
    }
}

// Development User Creation Modal
class DevUserModal {
    constructor() {
        this.modal = document.getElementById('addUserModal');
        this.form = document.getElementById('addUserForm');
        this.saveBtn = document.getElementById('saveUserBtn');
        this.alert = document.getElementById('addUserAlert');
        this.roleSelect = document.getElementById('roleSelect');
        
        if (!this.modal) return; // Only initialize if modal exists (dev mode)
        
        this.init();
    }
    
    init() {
        this.loadRoles();
        this.setupEventListeners();
    }
    
    async loadRoles() {
        try {
            const response = await fetch('/dev/roles');
            const roles = await response.json();
            
            this.roleSelect.innerHTML = '<option value="">Select a role...</option>';
            roles.forEach(role => {
                const option = document.createElement('option');
                option.value = role.id;
                option.textContent = role.name;
                this.roleSelect.appendChild(option);
            });
        } catch (error) {
            console.error('Failed to load roles:', error);
            this.showAlert('Failed to load roles', 'danger');
        }
    }
    
    setupEventListeners() {
        this.saveBtn.addEventListener('click', () => this.saveUser());
        
        // Clear form when modal is hidden
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.form.reset();
            this.hideAlert();
        });
    }
    
    async saveUser() {
        const formData = new FormData(this.form);
        const data = {
            first_name: formData.get('first_name'),
            last_name: formData.get('last_name'),
            email: formData.get('email'),
            role_id: formData.get('role_id')
        };
        
        // Basic validation
        if (!data.first_name || !data.last_name || !data.role_id) {
            this.showAlert('Please fill in all required fields', 'danger');
            return;
        }
        
        this.saveBtn.disabled = true;
        this.saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        
        try {
            const response = await fetch('/dev/add_user', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                setTimeout(() => {
                    // Close modal and reload page to show new user
                    const modalInstance = bootstrap.Modal.getInstance(this.modal);
                    modalInstance.hide();
                    window.location.reload();
                }, 1500);
            } else {
                this.showAlert(result.error || 'Failed to create user', 'danger');
            }
        } catch (error) {
            console.error('Error creating user:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        } finally {
            this.saveBtn.disabled = false;
            this.saveBtn.innerHTML = '<i class="fas fa-save"></i> Create User';
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development Beverage Management Modal
class DevBeverageModal {
    constructor() {
        this.modal = document.getElementById('addBeverageModal');
        this.form = document.getElementById('addBeverageForm');
        this.saveBtn = document.getElementById('saveBeverageBtn');
        this.alert = document.getElementById('addBeverageAlert');
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        this.saveBtn.addEventListener('click', () => this.saveBeverage());
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.form.reset();
            this.hideAlert();
        });
    }
    
    async saveBeverage() {
        const formData = new FormData(this.form);
        const data = {
            name: formData.get('name'),
            category: formData.get('category')
        };
        
        if (!data.name) {
            this.showAlert('Please enter an item name', 'danger');
            return;
        }
        
        this.saveBtn.disabled = true;
        this.saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        
        try {
            const response = await fetch('/dev/beverages', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                setTimeout(() => {
                    const modalInstance = bootstrap.Modal.getInstance(this.modal);
                    modalInstance.hide();
                }, 1500);
            } else {
                this.showAlert(result.error || 'Failed to create beverage', 'danger');
            }
        } catch (error) {
            console.error('Error creating beverage:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        } finally {
            this.saveBtn.disabled = false;
            this.saveBtn.innerHTML = '<i class="fas fa-save"></i> Create Beverage';
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development Price Management Modal
class DevPriceModal {
    constructor() {
        this.modal = document.getElementById('setPricesModal');
        this.container = document.getElementById('priceFormContainer');
        this.saveBtn = document.getElementById('savePricesBtn');
        this.alert = document.getElementById('setPricesAlert');
        this.beverages = [];
        this.roles = [];
        this.currentRoleId = null;
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.loadRoles();
        this.loadBeverages();
        this.setupEventListeners();
    }
    
    async loadRoles() {
        try {
            const response = await fetch('/dev/roles');
            this.roles = await response.json();
        } catch (error) {
            console.error('Failed to load roles:', error);
        }
    }
    
    async loadBeverages() {
        try {
            const response = await fetch('/dev/beverages');
            this.beverages = await response.json();
        } catch (error) {
            console.error('Failed to load beverages:', error);
        }
    }
    
    setupEventListeners() {
        // Load prices when modal opens
        this.modal.addEventListener('shown.bs.modal', () => this.showRoleSelection());
        this.saveBtn.addEventListener('click', () => this.savePrices());
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.container.innerHTML = '<p class="text-muted">Loading prices...</p>';
            this.saveBtn.style.display = 'none';
            this.hideAlert();
            this.currentRoleId = null;
        });
    }
    
    showRoleSelection() {
        let html = '<h6>Select a role to manage prices:</h6>';
        html += '<div class="row mb-3">';
        
        this.roles.forEach(role => {
            html += `
                <div class="col-md-6 mb-2">
                    <button class="btn btn-outline-primary w-100 role-select-btn" 
                            data-role-id="${role.id}" 
                            data-role-name="${role.name}">
                        <i class="fas fa-user-tag"></i> ${role.name}
                    </button>
                </div>
            `;
        });
        
        html += '</div>';
        html += '<div class="alert alert-info">';
        html += '<i class="fas fa-info-circle"></i> ';
        html += '<strong>Tip:</strong> You can set different prices for each role. ';
        html += 'Click on a role above to manage its specific prices.';
        html += '</div>';
        
        this.container.innerHTML = html;
        this.saveBtn.style.display = 'none';
        
        // Add event listeners to role buttons
        this.container.querySelectorAll('.role-select-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const roleId = parseInt(e.target.dataset.roleId);
                const roleName = e.target.dataset.roleName;
                this.loadPricesForRole(roleId, roleName);
            });
        });
    }
    
    async loadPricesForRole(roleId, roleName) {
        this.currentRoleId = roleId;
        
        // Load existing prices for this role
        let existingPrices = {};
        try {
            const response = await fetch(`/dev/prices?role_id=${roleId}`);
            const prices = await response.json();
            existingPrices = prices.reduce((acc, price) => {
                acc[price.beverage_id] = price.price_cents;
                return acc;
            }, {});
        } catch (error) {
            console.error('Failed to load existing prices:', error);
        }
        
        // Create price form for this role
        let html = `
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h6><i class="fas fa-user-tag"></i> Prices for Role: <strong>${roleName}</strong></h6>
                <button class="btn btn-outline-secondary btn-sm" onclick="devPriceModal.showRoleSelection()">
                    <i class="fas fa-arrow-left"></i> Back to Roles
                </button>
            </div>
        `;
        
        html += '<div class="row mb-2"><div class="col-6"><strong>Item</strong></div><div class="col-6"><strong>Price (cents)</strong></div></div>';
        
        this.beverages.forEach(beverage => {
            const existingPrice = existingPrices[beverage.id] || '';
            const categoryIcon = beverage.category === 'food' ? '🍽️' : '🥤';
            html += `
                <div class="row mb-2">
                    <div class="col-6">
                        <label class="form-label">${categoryIcon} ${beverage.name}</label>
                    </div>
                    <div class="col-6">
                        <input type="number" class="form-control price-input" 
                               data-beverage-id="${beverage.id}" 
                               value="${existingPrice}" 
                               placeholder="Price in cents" min="0" step="1">
                    </div>
                </div>
            `;
        });
        
        html += `
            <div class="mt-3">
                <button class="btn btn-outline-warning btn-sm" onclick="devPriceModal.setUnifiedPrices()">
                    <i class="fas fa-copy"></i> Copy these prices to all other roles
                </button>
            </div>
        `;
        
        this.container.innerHTML = html;
        this.saveBtn.style.display = 'block';
    }
    
    async savePrices() {
        if (!this.currentRoleId) {
            this.showAlert('Please select a role first', 'danger');
            return;
        }
        
        const priceInputs = this.container.querySelectorAll('.price-input');
        
        const prices = [];
        priceInputs.forEach(input => {
            const beverageId = input.dataset.beverageId;
            const priceCents = input.value;
            
            if (priceCents && priceCents > 0) {
                prices.push({
                    beverage_id: parseInt(beverageId),
                    price_cents: parseInt(priceCents)
                });
            }
        });
        
        if (prices.length === 0) {
            this.showAlert('Please set at least one price', 'danger');
            return;
        }
        
        this.saveBtn.disabled = true;
        this.saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Saving...';
        
        try {
            const response = await fetch('/dev/prices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    role_id: this.currentRoleId,
                    prices: prices
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                setTimeout(() => {
                    const modalInstance = bootstrap.Modal.getInstance(this.modal);
                    modalInstance.hide();
                }, 1500);
            } else {
                this.showAlert(result.error || 'Failed to save prices', 'danger');
            }
        } catch (error) {
            console.error('Error saving prices:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        } finally {
            this.saveBtn.disabled = false;
            this.saveBtn.innerHTML = '<i class="fas fa-save"></i> Save Prices';
        }
    }
    
    async setUnifiedPrices() {
        if (!this.currentRoleId) {
            this.showAlert('Please select a role first', 'danger');
            return;
        }
        
        const priceInputs = this.container.querySelectorAll('.price-input');
        
        const prices = [];
        priceInputs.forEach(input => {
            const beverageId = input.dataset.beverageId;
            const priceCents = input.value;
            
            if (priceCents && priceCents > 0) {
                prices.push({
                    beverage_id: parseInt(beverageId),
                    price_cents: parseInt(priceCents)
                });
            }
        });
        
        if (prices.length === 0) {
            this.showAlert('Please set at least one price first', 'danger');
            return;
        }
        
        if (!confirm('This will copy the current prices to ALL other roles. Are you sure?')) {
            return;
        }
        
        try {
            const response = await fetch('/dev/prices_unified', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prices: prices
                })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
            } else {
                this.showAlert(result.error || 'Failed to set unified prices', 'danger');
            }
        } catch (error) {
            console.error('Error setting unified prices:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development Role Management Modal
class DevRoleModal {
    constructor() {
        this.modal = document.getElementById('manageRolesModal');
        this.form = document.getElementById('addRoleForm');
        this.saveBtn = document.getElementById('saveRoleBtn');
        this.rolesList = document.getElementById('rolesList');
        this.alert = document.getElementById('manageRolesAlert');
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.loadRoles();
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        this.saveBtn.addEventListener('click', () => this.saveRole());
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.form.reset();
            this.hideAlert();
        });
    }
    
    async loadRoles() {
        try {
            const response = await fetch('/dev/roles_manage');
            const roles = await response.json();
            
            this.rolesList.innerHTML = '';
            roles.forEach(role => {
                const roleItem = document.createElement('div');
                roleItem.className = 'list-group-item d-flex justify-content-between align-items-center';
                roleItem.innerHTML = `
                    <div>
                        <span class="fw-bold">${role.name}</span>
                        <small class="text-muted d-block">ID: ${role.id}</small>
                    </div>
                    <button class="btn btn-outline-danger btn-sm" onclick="devRoleModal.deleteRole(${role.id}, '${role.name}')" title="Delete Role">
                        <i class="fas fa-trash"></i>
                    </button>
                `;
                this.rolesList.appendChild(roleItem);
            });
        } catch (error) {
            console.error('Failed to load roles:', error);
        }
    }
    
    async saveRole() {
        const formData = new FormData(this.form);
        const data = {
            name: formData.get('name')
        };
        
        if (!data.name) {
            this.showAlert('Please enter a role name', 'danger');
            return;
        }
        
        this.saveBtn.disabled = true;
        this.saveBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
        
        try {
            const response = await fetch('/dev/roles_manage', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                this.form.reset();
                this.loadRoles(); // Reload the roles list
            } else {
                this.showAlert(result.error || 'Failed to create role', 'danger');
            }
        } catch (error) {
            console.error('Error creating role:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        } finally {
            this.saveBtn.disabled = false;
            this.saveBtn.innerHTML = '<i class="fas fa-plus"></i> Add Role';
        }
    }
    
    async deleteRole(roleId, roleName) {
        if (!confirm(`Are you sure you want to delete the role "${roleName}"?\n\nThis action cannot be undone.`)) {
            return;
        }
        
        try {
            const response = await fetch(`/dev/delete_role/${roleId}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                this.loadRoles(); // Reload the roles list
            } else {
                this.showAlert(result.error || 'Failed to delete role', 'danger');
            }
        } catch (error) {
            console.error('Error deleting role:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development User Management Modal
class DevUserManagementModal {
    constructor() {
        this.modal = document.getElementById('manageUsersModal');
        this.usersList = document.getElementById('usersList');
        this.alert = document.getElementById('manageUsersAlert');
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        this.modal.addEventListener('shown.bs.modal', () => {
            this.loadUsers();
        });
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.hideAlert();
        });
    }
    
    async loadUsers() {
        try {
            const response = await fetch('/dev/users_manage');
            const users = await response.json();
            
            this.usersList.innerHTML = '';
            users.forEach(user => {
                const userItem = document.createElement('div');
                userItem.className = 'list-group-item d-flex justify-content-between align-items-center';
                userItem.innerHTML = `
                    <div>
                        <span class="fw-bold">${user.first_name} ${user.last_name}</span>
                        <small class="text-muted d-block">
                            Role: ${user.role_name} | 
                            Email: ${user.email || 'None'} | 
                            PIN: ${user.has_pin ? 'Set' : 'Not set'}
                        </small>
                    </div>
                    <button class="btn btn-outline-danger btn-sm" onclick="devUserManagementModal.deleteUser(${user.id}, '${user.first_name} ${user.last_name}')" title="Delete User">
                        <i class="fas fa-trash"></i>
                    </button>
                `;
                this.usersList.appendChild(userItem);
            });
        } catch (error) {
            console.error('Failed to load users:', error);
            this.showAlert('Failed to load users', 'danger');
        }
    }
    
    async deleteUser(userId, userName) {
        if (!confirm(`Are you sure you want to delete the user "${userName}"?\n\nThis will also delete all their consumptions and invoices.\n\nThis action cannot be undone.`)) {
            return;
        }
        
        try {
            const response = await fetch(`/dev/delete_user/${userId}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                this.loadUsers(); // Reload the users list
            } else {
                this.showAlert(result.error || 'Failed to delete user', 'danger');
            }
        } catch (error) {
            console.error('Error deleting user:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development Item Management Modal
class DevItemModal {
    constructor() {
        this.modal = document.getElementById('manageItemsModal');
        this.itemsList = document.getElementById('itemsList');
        this.alert = document.getElementById('manageItemsAlert');
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        this.modal.addEventListener('shown.bs.modal', () => {
            this.loadItems();
        });
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            this.hideAlert();
        });
    }
    
    async loadItems() {
        try {
            const response = await fetch('/dev/beverages');
            const items = await response.json();
            
            this.itemsList.innerHTML = '';
            items.forEach(item => {
                const itemElement = document.createElement('div');
                itemElement.className = 'list-group-item d-flex justify-content-between align-items-center';
                
                const categoryIcon = item.category === 'food' ? '🍽️' : '🥤';
                const categoryText = item.category === 'food' ? 'Food' : 'Drink';
                
                itemElement.innerHTML = `
                    <div>
                        <span class="fw-bold">${categoryIcon} ${item.name}</span>
                        <small class="text-muted d-block">
                            Category: ${categoryText} | ID: ${item.id}
                        </small>
                    </div>
                    <button class="btn btn-outline-danger btn-sm" onclick="devItemModal.deleteItem(${item.id}, '${item.name}', '${item.category}')" title="Delete Item">
                        <i class="fas fa-trash"></i>
                    </button>
                `;
                this.itemsList.appendChild(itemElement);
            });
        } catch (error) {
            console.error('Failed to load items:', error);
            this.showAlert('Failed to load items', 'danger');
        }
    }
    
    async deleteItem(itemId, itemName, itemCategory) {
        const categoryText = itemCategory === 'food' ? 'food item' : 'beverage';
        
        try {
            // First, try to delete without force
            const response = await fetch(`/dev/delete_beverage/${itemId}`, {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' }
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                this.loadItems(); // Reload the items list
                return;
            }
            
            // If deletion failed due to related data, show warning dialog
            if (result.has_related_data) {
                const priceText = result.price_count > 0 ? `${result.price_count} price(s)` : '';
                const consumptionText = result.consumption_count > 0 ? `${result.consumption_count} consumption(s)` : '';
                const relatedDataText = [priceText, consumptionText].filter(Boolean).join(' and ');
                
                const warningMessage = `The ${categoryText} "${itemName}" has ${relatedDataText} associated with it.\n\n` +
                    `If you delete it, ALL related data will be permanently removed:\n` +
                    `- All consumption records for this item\n` +
                    `- All price settings for this item\n\n` +
                    `This action cannot be undone!\n\n` +
                    `Do you want to proceed with deletion?`;
                
                if (confirm(warningMessage)) {
                    // User confirmed, try deletion with force_delete
                    const forceResponse = await fetch(`/dev/delete_beverage/${itemId}`, {
                        method: 'DELETE',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ force_delete: true })
                    });
                    
                    const forceResult = await forceResponse.json();
                    
                    if (forceResult.success) {
                        this.showAlert(forceResult.message, 'success');
                        this.loadItems(); // Reload the items list
                    } else {
                        this.showAlert(forceResult.error || 'Failed to delete item', 'danger');
                    }
                }
            } else {
                // Other error
                this.showAlert(result.error || 'Failed to delete item', 'danger');
            }
        } catch (error) {
            console.error('Error deleting item:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Development Data Deletion Modal
class DevDeleteModal {
    constructor() {
        this.modal = document.getElementById('deleteDataModal');
        this.confirmBtn = document.getElementById('confirmDeleteBtn');
        this.alert = document.getElementById('deleteDataAlert');
        
        if (!this.modal) return;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        this.confirmBtn.addEventListener('click', () => this.deleteData());
        
        this.modal.addEventListener('hidden.bs.modal', () => {
            // Uncheck all checkboxes
            const checkboxes = this.modal.querySelectorAll('input[type="checkbox"]');
            checkboxes.forEach(cb => cb.checked = false);
            this.hideAlert();
        });
    }
    
    async deleteData() {
        const checkboxes = this.modal.querySelectorAll('input[type="checkbox"]:checked');
        const deleteTypes = Array.from(checkboxes).map(cb => cb.value);
        
        if (deleteTypes.length === 0) {
            this.showAlert('Please select at least one data type to delete', 'danger');
            return;
        }
        
        this.confirmBtn.disabled = true;
        this.confirmBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Deleting...';
        
        try {
            const response = await fetch('/dev/delete_data', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delete_types: deleteTypes })
            });
            
            const result = await response.json();
            
            if (result.success) {
                this.showAlert(result.message, 'success');
                setTimeout(() => {
                    const modalInstance = bootstrap.Modal.getInstance(this.modal);
                    modalInstance.hide();
                    window.location.reload(); // Reload to reflect changes
                }, 2000);
            } else {
                this.showAlert(result.error || 'Failed to delete data', 'danger');
            }
        } catch (error) {
            console.error('Error deleting data:', error);
            this.showAlert('Network error. Please try again.', 'danger');
        } finally {
            this.confirmBtn.disabled = false;
            this.confirmBtn.innerHTML = '<i class="fas fa-trash"></i> Delete Selected';
        }
    }
    
    showAlert(message, type) {
        this.alert.className = `alert alert-${type}`;
        this.alert.textContent = message;
        this.alert.style.display = 'block';
    }
    
    hideAlert() {
        this.alert.style.display = 'none';
    }
}

// Guests Button Handler
class GuestsButton {
    constructor() {
        this.guestsBtn = document.getElementById('guestsBtn');
        this.init();
    }
    
    init() {
        if (this.guestsBtn) {
            this.guestsBtn.addEventListener('click', () => this.handleGuestsClick());
        }
    }
    
    handleGuestsClick() {
        // Navigate to the guests page
        window.location.href = '/guests';
    }
}

// Initialize everything when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    new UserSearch();
    new UserClickHandler();
    new GuestsButton();
    new DevUserModal();
    new DevBeverageModal();
    new DevPriceModal();
    new DevRoleModal();
    new DevUserManagementModal();
    new DevItemModal();
    new DevDeleteModal();
    
    // Make modals globally accessible for onclick handlers
    window.devRoleModal = new DevRoleModal();
    window.devUserManagementModal = new DevUserManagementModal();
    window.devItemModal = new DevItemModal();
    window.devPriceModal = new DevPriceModal();
});