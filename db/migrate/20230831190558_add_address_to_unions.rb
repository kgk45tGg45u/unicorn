class AddAddressToUnions < ActiveRecord::Migration[7.0]
  def change
    add_column :unions, :address, :text
  end
end
