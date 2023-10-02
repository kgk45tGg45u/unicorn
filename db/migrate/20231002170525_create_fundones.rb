class CreateFundones < ActiveRecord::Migration[7.0]
  def change
    create_table :fundones do |t|
      t.integer :balance

      t.timestamps
    end
  end
end
